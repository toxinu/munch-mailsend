import os
import re

from setuptools import setup
from setuptools import find_packages

with open(os.path.join(os.path.dirname(__file__), 'README.rst')) as readme:
    README = readme.read()

os.chdir(os.path.normpath(os.path.join(os.path.abspath(__file__), os.pardir)))

with open('munch_mailsend/__init__.py', 'r') as fd:
    version = re.search(
        r'^__version__\s*=\s*[\'"]([^\'"]*)[\'"]',
        fd.read(), re.MULTILINE).group(1)

if not version:
    raise RuntimeError('Cannot find version information')


def _find_packages(name):
    return [name] + ['{}/{}'.format(name, f) for f in find_packages(name)]


setup(
    name='munch-mailsend',
    version=version,
    packages=_find_packages('munch_mailsend') + \
        _find_packages('munch_mailsend_tests'),
    long_description=README,
    include_package_data=True,
    license='GNU AGPLv3',
    description='Sending mass emails with Munch.',
    author='Geoffrey Lehée',
    author_email='glehee@oasiswork.fr',
    url='https://github/crunchmail/munch-mailsend',
    install_requires=[],
    extras_require={
        'tests': [
            'flake8==2.5.4',
            'bumpversion==0.5.3',
            'libfaketime==0.2.1']},
    classifiers=[
        'Environment :: Web Environment',
        'Framework :: Django',
        'Framework :: Django :: 1.9',
        'Intended Audience :: Developers',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Topic :: Internet :: WWW/HTTP',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
        'License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)',  # noqa
    ]
)
