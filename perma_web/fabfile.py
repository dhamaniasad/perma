from functools import wraps
import shutil
import sys, os
from datetime import date
import tempfile
from django.utils.crypto import get_random_string
from fabric.api import *
import subprocess
from perma.models import LinkUser, Folder

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'perma.settings')
from django.conf import settings


### SETUP ###
env.REMOTE_DIR = None
env.VIRTUALENV_NAME = None
env.SETUP_PREFIXES = None # list of prefixes to run in setup_remote, e.g. [prefix('do stuff')]
env.PYTHON_BIN = 'python'
WSGI_FILE = 'perma/wsgi.py'
LOCAL_DB_SETTINGS = settings.DATABASES['default']
env.DATABASE_BACKUP_DIR = None # If relative path, dir is relative to REMOTE_DIR. If None, no backup will be done.

_already_setup = False
def setup_remote(f):
    """
        Decorator to make sure we're running things in the right remote directory,
        with the virtualenv set up.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        global _already_setup
        if not _already_setup:
            _already_setup = True
            def apply_withs(withs, target_func):
                if withs:
                    with withs[0]:
                        return apply_withs(withs[1:], target_func)
                return target_func()
            prefixes = [cd(env.REMOTE_DIR)]
            if env.VIRTUALENV_NAME:
                prefixes.append(prefix("workon "+env.VIRTUALENV_NAME))
            if env.SETUP_PREFIXES:
                prefixes += env.SETUP_PREFIXES
            return apply_withs(prefixes, lambda: f(*args, **kwargs))
        return f(*args, **kwargs)
    return wrapper


### GENERAL UTILITIES ###

def run(port="0.0.0.0:8000"):
    """
        Run django test server on open port, so it's accessible outside Vagrant.
    """
    local("python manage.py runserver %s" % port)

def test(apps="perma mirroring"):
    """
        Run perma tests. (For coverage, run `coverage report` after tests pass.)
    """
    excluded_files = [
        "perma/migrations/*",
        "*/tests/*",
        "fabfile.py",
        "mirroring/management/commands/runmirror.py"
    ]
    local("coverage run --source='.' --omit='%s' manage.py test %s" % (",".join(excluded_files), apps))

def test_sauce(target_host="127.0.0.1:8000"):
    """
        Run Sauce browser tests. If target_host is localhost, first run sauce_tunnel.
    """
    os.environ.setdefault('SAUCE_USERNAME', settings.SAUCE_USERNAME)
    os.environ.setdefault('SAUCE_ACCESS_KEY', settings.SAUCE_ACCESS_KEY)

    local("HOST="+target_host+" " +
          "py.test " +
          "-n3 " +  # run 3 in parallel - max for free account
          "--boxed " +  # don't let crashes in single test kill whole process
          os.path.join(settings.PROJECT_ROOT, "../services/sauce/run_tests.py"))

def sauce_tunnel():
    """
        Set up Sauce tunnel before running test_sauce targeted at localhost.
    """
    if subprocess.call(['which','sc']) == 1: # error return code -- program not found
        sys.exit("Please check that the `sc` program is installed and in your path. To install: https://docs.saucelabs.com/reference/sauce-connect/")
    local("sc -u %s -k %s" % (settings.SAUCE_USERNAME, settings.SAUCE_ACCESS_KEY))


def logs(log_dir=os.path.join(settings.PROJECT_ROOT, '../services/logs/')):
    """ Tail all logs. """
    local("tail -f %s/*" % log_dir)

def init_dev_db():
    """
        Run syncdb, South migrate, and import fixtures for new dev database.
    """
    local("python manage.py syncdb --noinput")
    local("python manage.py migrate")
    local("python manage.py loaddata fixtures/users.json fixtures/groups.json")

def south_out(app="perma"):
    """
        Migrate schema changes out of models.py to migration files.
    """
    local("python manage.py schemamigration %s --auto" % app)

def south_in(*args):
    """
        Migrate schema changes from migration files into db. For single app, do fab south_in:app_name
    """
    local("python manage.py migrate %s" % (" ".join(args)))


### DEPLOYMENT ###

@setup_remote
def deploy(branch='master'):
    """
        Full deployment: back up database, pull code, install requirements, sync db, run south migrations, collect static files, restart server.
    """
    backup_database()
    deploy_code(restart=False, branch=branch)
    pip_install()
    run("%s manage.py syncdb" % env.PYTHON_BIN)
    run("fab south_in")
    run("%s manage.py collectstatic --noinput --clear" % env.PYTHON_BIN)
    

@setup_remote
def deploy_code(restart=True, branch='master'):
    """
        Deploy code only. This is faster than the full deploy.
    """
    run("git pull origin %s" % branch)
    if restart:
          restart_server()
          
def pip_install():
      run("pip install -r requirements.txt")

@setup_remote
def restart_server():
    """
        Touch the wsgi file to restart the remote server (hopefully).
    """
    run("cd /srv/www/perma/perma_web && set -m ; (service gunicorn stop; sleep 1; service gunicorn start)&")
    run("sudo service celery stop; sudo service celery start;")
    run("sudo service celerybeat stop; sudo service celerybeat start;")


@setup_remote
def stop_server():
    """
        Stop the services
    """
    run("sudo service gunicorn stop")
    run("sudo service celery stop")
    run("sudo service celerybeat stop")
    
    
@setup_remote
def start_server():
    """
        Start the services
    """
    run("sudo service gunicorn start")
    run("sudo service celery start")
    run("sudo service celerybeat start")

### DATABASE STUFF ###

@setup_remote
def backup_database():
    if env.DATABASE_BACKUP_DIR:
        run("fab local_backup_database:%s" % env.DATABASE_BACKUP_DIR)

def local_backup_database(backup_dir):
    # WARNING: this is totally untested
    # this is going to be triggered by calling fab on the remote server, so that LOCAL_DB_SETTINGS has the remote settings
    import pexpect
    child = pexpect.spawn(r"""mysqldump --user={user} {database} | gzip > {backup_dir}/{date}.sql.gz""".format(
        user=LOCAL_DB_SETTINGS['USER'],
        database=LOCAL_DB_SETTINGS['NAME'],
        backup_dir=backup_dir,
        date=date.today().isoformat()
    ))
    child.expect('Enter password:')
    child.sendline(LOCAL_DB_SETTINGS['PASSWORD'])

@setup_remote
def shell():
    """
        Handy way to drop into remote shell with Django stuff set up.
    """
    from fabric.context_managers import char_buffered
    with char_buffered(sys.stdin):
        open_shell("cd %s && workon %s" % (env.REMOTE_DIR, env.VIRTUALENV_NAME))


### MIRRORING ###

def sync_mirror():
    """
        Fetch all archived links from upstream.
    """
    from mirroring.tasks import sync_mirror
    sync_mirror()


### HEROKU ###

def heroku_create_app(app_name, s3_storage_bucket=None):
    """
        Set up a new Heroku Perma app.
    """
    def heroku(cmd):
        local("heroku %s --app %s" % (cmd, app_name))

    #heroku("apps:create %s" % app_name)
    heroku("config:add BUILDPACK_URL=git://github.com/jcushman/heroku-buildpack-python.git")
    heroku("addons:add cleardb:ignite")
    heroku("addons:add cloudamqp")
    heroku("addons:add redistogo")

    # Django config
    if not s3_storage_bucket:
        s3_storage_bucket = app_name
    s3_url = 'http://%s.s3.amazonaws.com/' % s3_storage_bucket
    django_config_vars = {
        'SECRET_KEY':get_random_string(50, 'abcdefghijklmnopqrstuvwxyz0123456789'),
        'ARCHIVE_URL':s3_url+'generated/',
        'AWS_STORAGE_BUCKET_NAME':s3_storage_bucket,
        'CDX_SERVER_URL':'http://%s.herokuapp.com/cdx' % app_name,
        'HOST':'%s.herokuapp.com' % app_name,
        'PYWB_ARCHIVE_LOCATION':s3_url+'generated/',
        'STATIC_URL':s3_url+'static/',
        'MEDIA_URL':s3_url+'media/',
    }
    for key, val in django_config_vars.items():
        heroku("config:set DJANGO__%s=%s" % (key, val))

    print "Heroku app setup completed. Remember to set DJANGO__HOST to the correct domain," +\
          "and DJANGO__AWS_ACCESS_KEY_ID and DJANGO__AWS_SECRET_ACCESS_KEY to your credentials."

def heroku_push(app_name='perma', project_dir=os.path.join(settings.PROJECT_ROOT, '..')):
    """
        Push code to Heroku.
    """
    # where we'll get files from to set up the heroku deployment
    heroku_files_dir = os.path.join(project_dir, "services", "heroku")

    # copy perma_web to a temp dir for deployment
    dest_dir = tempfile.mkdtemp()
    local("cp -r %s/* %s" % (os.path.join(project_dir, "perma_web"), dest_dir))

    with lcd(dest_dir):

        # set up heroku files
        local("cp -r %s ." % os.path.join(heroku_files_dir, "bin"))
        local("cp %s ." % os.path.join(heroku_files_dir, "Procfile"))
        local("cp %s perma/" % os.path.join(heroku_files_dir, "wsgi_heroku.py"))
        local("cp %s perma/settings/" % os.path.join(heroku_files_dir, "settings.py"))
        local("cat %s >> requirements.txt" % os.path.join(heroku_files_dir, "extra_requirements.txt"))

        # set up git
        local(r'sed "s/perma_web\/perma\/settings\/settings.py|perma_web\///g" %s/%s > %s' % (project_dir, '.gitignore', '.gitignore'))
        local("git init")
        local("git add -A")
        local("git commit -m 'heroku push `date`'")
        local("heroku git:remote -a %s" % app_name)

        # push to heroku
        local("git push --force heroku master")

    # delete temp dir
    shutil.rmtree(dest_dir)


try:
    from fab_targets import *
except ImportError, e:
    if e.message=='No module named fab_targets':
        print "Warning: no fab_targets file found."
    else:
        raise