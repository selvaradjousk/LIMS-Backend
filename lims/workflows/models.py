from django.db import models
from django.contrib.auth.models import User

from jsonfield import JSONField

from lims.projects.models import Product
from lims.equipment.models import Equipment
from lims.inventory.models import Item, ItemType, ItemTransfer, AmountMeasure
from lims.filetemplate.models import FileTemplate
from lims.datastore.models import DataFile


class Workflow(models.Model):
    name = models.CharField(max_length=50)
    order = models.CommaSeparatedIntegerField(max_length=200, blank=True)
    created_by = models.ForeignKey(User)
    date_created = models.DateTimeField(auto_now_add=True)

    class Meta:
        permissions = (
            ('view_workflow', 'View workflow',),
        )

    def get_tasks(self):
        if self.order:
            order = [int(v) for v in self.order.split(',')]
            tasks = list(TaskTemplate.objects.filter(pk__in=order))
            ordered_tasks = []
            for o in order:
                ordered_tasks.append(next((obj for obj in tasks if obj.id == o), None))
            return ordered_tasks
        return []

    def get_task_at_index(self, index):
        if self.order:
            order = [int(v) for v in self.order.split(',')]
            try:
                return TaskTemplate.objects.get(pk=order[index])
            except TaskTemplate.DoesNotExist:
                return None
        return None

    def __str__(self):
        return self.name


class RunLabware(models.Model):
    """
    Specifies labware associated with a run
    """
    identifier = models.CharField(max_length=100, db_index=True)
    labware = models.ForeignKey(Item)
    is_active = models.BooleanField(default=False)
    # Need some way of mapping a something to a location
    # so we can have plate maps etc.
    # Ignore this for now!

    def __str__(self):
        return '{}: {}'.format(self.identifier, self.item.name)


class Run(models.Model):
    """
    Takes a series of tasks (e.g. from a workflow) and runs products through them

    At end of run is marked inactive for tracking of historical data.
    """
    name = models.CharField(max_length=100, blank=True, null=True)

    tasks = models.CommaSeparatedIntegerField(max_length=400, blank=True)
    # Cannot be at different stages on a run, start a new one if there
    # are issues (e.g. failures) as these need plates changing etc.
    current_task = models.IntegerField(default=0)
    task_in_progress = models.BooleanField(default=False)
    # Created/updated at the start of every task.
    task_run_identifier = models.UUIDField(null=True, blank=True)

    products = models.ManyToManyField(Product, blank=True,
                                      related_name='run')
    labware = models.ManyToManyField(RunLabware, blank=True,
                                     related_name='run_labware')
    transfers = models.ManyToManyField(ItemTransfer, blank=True,
                                       related_name='run_transfers')

    # If run has not completed all tasks, allows for run archiving
    is_active = models.BooleanField(default=True)
    # If the run has started (e.g. for preventing adding more products)
    has_started = models.BooleanField(default=False)

    date_started = models.DateTimeField(auto_now_add=True)
    date_finished = models.DateTimeField(blank=True, null=True)
    started_by = models.ForeignKey(User)

    def get_task_list(self):
        """
        Get list of task IDs
        """
        return [int(v) for v in self.tasks.split(',')]

    def get_tasks(self):
        """
        Get an ordered list of tasks for this run
        """
        if self.tasks:
            task_list = [int(v) for v in self.tasks.split(',')]
            tasks = list(TaskTemplate.objects.filter(pk__in=task_list))
            ordered_tasks = []
            for t in task_list:
                ordered_tasks.append(next((obj for obj in tasks if obj.id == t), None))
            return ordered_tasks
        return []

    def get_task_at_index(self, index):
        """
        Get a single task at the provided index
        """
        if self.tasks:
            task_list = [int(v) for v in self.tasks.split(',')]
            try:
                return TaskTemplate.objects.get(pk=task_list[index])
            except TaskTemplate.DoesNotExist:
                return None
        return None

    def has_valid_inputs(self):
        task = self.get_task_at_index(self.current_task)
        valid = {}
        if task:
            for p in self.products.all():
                if p.linked_inventory.filter(item_type=task.product_input).count() > 0:
                    valid[p.id] = True
                else:
                    valid[p.id] = False
            return valid
        return False

    class Meta:
        ordering = ['-date_started']
        permissions = (
            ('view_run', 'View run',),
        )

    def __str__(self):
        if self.is_active:
            return '{}, started by: {} on {}'.format(self.identifier,
                                                     self.started_by.username,
                                                     self.date_started)
        return '{}, started by: {} finished on {}'.format(self.identifier,
                                                          self.started_by.username,
                                                          self.date_finished)


class DataEntry(models.Model):

    STATE = (
        ('active', 'In Progress'),
        ('succeeded', 'Succeded'),
        ('failed', 'Failed'),
        ('repeat succeeded', 'Repeat succeded'),
        ('repeat failed', 'Repeat Failed'),
    )

    run = models.ForeignKey(Run, null=True, related_name='data_entries')
    # Unique identifier for the task/run combo
    task_run_identifier = models.UUIDField(db_index=True)

    product = models.ForeignKey(Product, related_name='data')
    item = models.ForeignKey(Item, null=True, related_name='data_entries')
    date_created = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User)
    state = models.CharField(max_length=20, choices=STATE)
    data = JSONField()
    data_files = models.ManyToManyField(DataFile, blank=True)

    task = models.ForeignKey('TaskTemplate')

    def __str__(self):
        return '{}: {}, {}'.format(self.date_created, self.workflow, self.task)

    class Meta:
        ordering = ['-date_created']


class TaskTemplate(models.Model):

    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)

    # The main input to take from the Inventory based on what
    # is attached to the Product
    product_input = models.ForeignKey(ItemType, related_name='product_input')
    product_input_amount = models.IntegerField()
    product_input_measure = models.ForeignKey(AmountMeasure)

    labware = models.ForeignKey(ItemType, related_name='labware')
    labware_amount = models.IntegerField(default=1)
    multiple_products_on_labware = models.BooleanField(default=False)

    capable_equipment = models.ManyToManyField(Equipment, blank=True)

    input_files = models.ManyToManyField(
        FileTemplate, blank=True, related_name='input_file_templates')
    output_files = models.ManyToManyField(
        FileTemplate, blank=True, related_name='output_file_templates')

    created_by = models.ForeignKey(User)
    date_created = models.DateTimeField(auto_now_add=True)

    class Meta:
        permissions = (
            ('view_tasktemplate', 'View workflow task template',),
        )

    def store_labware_as(self):
        return 'labware_identifier'

    def __str__(self):
        return self.name


class CalculationFieldTemplate(models.Model):
    """
    Store a calculation referenceing variables and inputs
    """
    template = models.ForeignKey(TaskTemplate, related_name='calculation_fields')
    label = models.CharField(max_length=50)
    description = models.CharField(max_length=200, null=True, blank=True)

    calculation = models.TextField()
    result = models.FloatField(null=True, blank=True)

    def field_name(self):
        return self.label.lower().replace(' ', '_')

    def __str__(self):
        return self.label


class InputFieldTemplate(models.Model):
    """
    An input to a task.

    Can read amounts from either a calculationor an input file
    """
    template = models.ForeignKey(TaskTemplate, related_name='input_fields')
    label = models.CharField(max_length=50)
    description = models.CharField(max_length=200, null=True, blank=True)
    amount = models.FloatField()
    measure = models.ForeignKey(AmountMeasure)
    lookup_type = models.ForeignKey(ItemType)

    from_input_file = models.BooleanField(default=False)
    from_calculation = models.BooleanField(default=False)
    calculation_used = models.ForeignKey(CalculationFieldTemplate, null=True, blank=True)

    def field_name(self):
        return self.label.lower().replace(' ', '_')

    def store_value_in(self):
        return 'inventory_identifier'

    def __str__(self):
        return self.label


class VariableFieldTemplate(models.Model):
    template = models.ForeignKey(TaskTemplate, related_name='variable_fields')
    label = models.CharField(max_length=50)
    description = models.CharField(max_length=200, null=True, blank=True)
    amount = models.FloatField()
    measure = models.ForeignKey(AmountMeasure, blank=True, null=True)
    measure_not_required = models.BooleanField(default=False)

    def field_name(self):
        return self.label.lower().replace(' ', '_')

    def __str__(self):
        return self.label


class OutputFieldTemplate(models.Model):
    template = models.ForeignKey(TaskTemplate, related_name='output_fields')
    label = models.CharField(max_length=50)
    description = models.CharField(max_length=200, null=True, blank=True)
    amount = models.FloatField()
    measure = models.ForeignKey(AmountMeasure)
    lookup_type = models.ForeignKey(ItemType)

    from_calculation = models.BooleanField(default=False)
    calculation_used = models.ForeignKey(CalculationFieldTemplate, null=True, blank=True)

    def field_name(self):
        return self.label.lower().replace(' ', '_')

    def __str__(self):
        return self.label


class StepFieldTemplate(models.Model):
    template = models.ForeignKey(TaskTemplate, related_name='step_fields')
    label = models.CharField(max_length=50)
    description = models.CharField(max_length=200, null=True, blank=True)

    def field_name(self):
        return self.label.lower().replace(' ', '_')

    def __str__(self):
        return self.label


class StepFieldProperty(models.Model):
    step = models.ForeignKey(StepFieldTemplate, related_name='properties')
    label = models.CharField(max_length=50)
    amount = models.FloatField()
    measure = models.ForeignKey(AmountMeasure)

    from_calculation = models.BooleanField(default=False)
    calculation_used = models.ForeignKey(CalculationFieldTemplate, null=True, blank=True)

    def field_name(self):
        return self.label.lower().replace(' ', '_')

    def __str__(self):
        return self.label
