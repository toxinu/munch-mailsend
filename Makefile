DJANGO_SETTINGS_MODULE ?= munch_mailsend_tests.settings

default:
	@echo "Must call a specific subcommand"
	@exit 1

release:
	@echo "Releasing \"`python setup.py --version`\" on Pypi in 5 seconds..."
	@sleep 5
	python setup.py sdist bdist_wheel upload

test:
	munch django test munch_mailsend_tests --settings=munch_mailsend_tests.settings

.PHONY: release test
