# Hand-written: makemigrations prompts for a one-off default when a nullable
# column becomes NOT NULL. No default is appropriate; every existing row must
# already carry a level before this migration runs.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0029_alter_staffteachingduty_subject_and_more'),
        ('integrations', '0008_emisteacherlinktype_needs_renewal'),
    ]

    operations = [
        migrations.AlterField(
            model_name='schoolstaffassignment',
            name='teacher_level_type',
            field=models.ForeignKey(help_text='Education level (Primary/JSS/SSS) for this assignment', on_delete=django.db.models.deletion.PROTECT, related_name='staff_assignments', to='integrations.emiseducationlevel', verbose_name='Education level'),
        ),
    ]
