# Generated by Django 2.2.10 on 2020-02-18 19:47

from django.db import migrations, models
import django.utils.timezone
import jsonfield.fields


class Migration(migrations.Migration):

    dependencies = [
        ('news', '0017_auto_20190627_2116'),
    ]

    operations = [
        migrations.CreateModel(
            name='CommonVoiceUpdate',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('when', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('data', jsonfield.fields.JSONField(default=dict)),
                ('ack', models.BooleanField(default=False)),
            ],
            options={
                'ordering': ['pk'],
            },
        ),
    ]