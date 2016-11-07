from django.db import models
import reversion
import six
from django.contrib.auth.models import User
from django.dispatch import receiver
from django.db.models.signals import post_save
from django.core.mail import send_mail
from lims.settings import ALERT_EMAIL_FROM


@reversion.register()
class Organism(models.Model):
    """
    Basic information on an Organism
    """
    name = models.CharField(max_length=100)
    common_name = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return self.name


@reversion.register()
class LimsPermission(models.Model):
    """
    Allow access to the LIMS system
    """

    class Meta:
        permissions = (
            ('lims_access', 'Access LIMS system',),
        )


@reversion.register()
class TriggerSet(models.Model):
    LOW = 'L'
    MEDIUM = 'M'
    HIGH = 'H'
    SEVERITY_CHOICES = {
        LOW: 'low',
        MEDIUM: 'medium',
        HIGH: 'high'
    }
    model = models.CharField(blank=False, null=False, default='Item')
    severity = models.CharField(blank=False, null=False, max_length=1, choices=SEVERITY_CHOICES,
                                default=LOW)
    name = models.CharField(blank=False, null=False, default="My Trigger")
    emailTitle = models.CharField(blank=False, null=False, default='Alert from GET LIMS')
    emailTemplate = \
        models.CharField(blank=False, null=False,
                         default='{name}: {model} instance {instance} triggered on {date}.')

    @staticmethod
    @receiver(post_save, dispatch_uid='Fire Triggers')
    def fire_trigger(sender, instance=None, created=False, **kwargs):
        model = sender.__name__
        for triggerSet in TriggerSet.objects.filter(model=model).all():
            if triggerSet.all_triggers_fire(instance):
                email_recipients = []
                alert = TriggerAlert.objects.create(triggerSet=triggerSet, instanceId=instance.id)
                for subscription in triggerSet.subscriptions.all():
                    if subscription.email:
                        email_recipients.append(subscription.user.email)
                    status = TriggerAlertStatus.objects.create(user=subscription.user,
                                                               status=TriggerAlertStatus.ACTIVE,
                                                               lastUpdatedBy=subscription.user,
                                                               triggerAlert=alert)
                    status.save()
                alert.save()
                if len(email_recipients) > 0:
                    content = triggerSet.complete_email_template(instance, alert.fired)
                    send_mail(
                        triggerSet.emailTitle,
                        content,
                        ALERT_EMAIL_FROM,
                        email_recipients,
                        fail_silently=False,
                    )

    def all_triggers_fire(self, instance):
        for trigger in self.triggers.all():
            if not trigger.trigger_fires(instance):
                return False
        return True

    def complete_email_template(self, instance, fired):
        content = self.emailTemplate
        replace_fields = {
            "model": self.model,
            "instance": instance.id,
            "name": self.name,
            "date": fired.strftime("%Y-%m-%d %H:%M:%S")
        }
        for field, value in replace_fields:
            content = content.replace('{{{}}}'.format(field), value)
        return content


@reversion.register()
class Trigger(models.Model):
    EQ = '='
    LE = '<='
    GE = '>='
    LT = '<'
    GT = '>'
    NE = '!='
    OPERATOR_CHOICES = {
        LT: 'less than',
        LE: 'less than or equal to',
        EQ: 'equal to',
        GE: 'greater than or equal to',
        GT: 'greater than',
        NE: 'not equal to'
    }
    triggerSet = models.ForeignKey(TriggerSet, related_name="triggers")
    field = models.CharField(blank=False, null=False, default='id')
    operator = models.CharField(blank=False, null=False, max_length=2, choices=OPERATOR_CHOICES,
                                default=EQ)
    value = models.CharField(blank=False, null=False, default='1')

    def trigger_fires(self, instance):
        if hasattr(instance, self.field):
            test_value = self.value
            instance_value = getattr(instance, self.field)
            if isinstance(instance_value, six.string_types):
                # Wrap only strings in quotes
                test_value = "'%s'" % self.value
                instance_value = "'%s'" % instance_value
            expr = '%s%s%s' % (instance_value, self.operator, test_value)
            return eval(expr, {"__builtins__": {}})
        return False


@reversion.register()
class TriggerAlert(models.Model):
    triggerSet = models.ForeignKey(TriggerSet, related_name="alerts")
    fired = models.DateTimeField(auto_now_add=True)
    instanceId = models.IntegerField()


@reversion.register()
class TriggerAlertStatus(models.Model):
    ACTIVE = 'A'
    SILENCED = 'S'
    DISMISSED = 'D'
    STATUS_CHOICES = {
        ACTIVE: 'Active',
        SILENCED: 'Silenced',
        DISMISSED: 'Dismissed'
    }
    user = models.ManyToManyField(User)
    status = models.CharField(blank=False, null=False, max_length=1, choices=STATUS_CHOICES,
                              default=ACTIVE)
    lastUpdated = models.DateTimeField(auto_now=True)
    lastUpdatedBy = models.ForeignKey(User)
    triggerAlert = models.ForeignKey(TriggerAlert, related_name="statuses")


@reversion.register()
class TriggerSubscription(models.Model):
    triggerSet = models.ForeignKey(TriggerSet, related_name="subscriptions")
    user = models.ForeignKey(User)
    email = models.BooleanField(default=False, blank=False, null=False, )
