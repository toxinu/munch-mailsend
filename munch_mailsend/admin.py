from django.contrib import admin

from .models import Worker
from .models import Mail
from .models import MailStatus


class WorkerAdmin(admin.ModelAdmin):
    list_filter = ['enabled', 'creation_date', 'update_date']
    list_display = ['ip', 'name', 'creation_date', 'update_date', 'enabled']


class MailStatusInline(admin.TabularInline):
    extra = 0
    max_num = 0
    can_delete = False
    model = MailStatus
    ordering = ['creation_date']
    readonly_fields = [
        'source_ip', 'destination_domain', 'status_code',
        'source_hostname', 'raw_msg', 'creation_date', 'status']


class MailAdmin(admin.ModelAdmin):
    list_display = [
        'identifier', 'creation_date', 'had_delay', 'sender', 'recipient']
    list_filter = ['creation_date', 'had_delay']
    search_fields = ['identifier', 'sender', 'recipient']
    inlines = [MailStatusInline]
    readonly_fields = [
        'creation_date', 'identifier', 'delivery_duration',
        'first_status_date', 'latest_status_date']


class MailStatusAdmin(admin.ModelAdmin):
    search_fields = ['mail__identifier', 'destination_domain']
    list_display = ['mail_id', 'status', 'creation_date', 'destination_domain']
    list_filter = ['status', 'creation_date']
    readonly_fields = ['creation_date', 'destination_domain']
    raw_id_fields = ['mail']


admin.site.register(Mail, MailAdmin)
admin.site.register(Worker, WorkerAdmin)
admin.site.register(MailStatus, MailStatusAdmin)
