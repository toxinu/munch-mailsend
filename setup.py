import os

from setuptools import setup
from setuptools import find_packages

base_dir = os.path.dirname(__file__)

about = {}
with open(os.path.join(base_dir, "munch_mailsend", "__about__.py")) as f:
    exec(f.read(), about)

with open(os.path.join(base_dir, "README.rst")) as f:
    long_description = f.read()


def _find_packages(name):
    return [name] + ['{}/{}'.format(name, f) for f in find_packages(name)]


setup(
    name=about["__title__"],
    version=about["__version__"],
    packages=_find_packages('munch_mailsend') + \
        _find_packages('munch_mailsend_tests'),
    long_description=long_description,
    license=about["__version__"],
    description=about["__summary__"],
    author=about["__author__"],
    author_email=about["__email__"],
    url=about["__uri__"],
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
