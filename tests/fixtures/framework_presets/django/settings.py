"""Django settings fixture - DEBUG left on is the SAFE905 trigger.

Every positive case has a negative control in the same fixture set so
the e2e assertions double as a "what does idiomatic framework code look
like under each rule?" reference.
"""

DEBUG = True

ALLOWED_HOSTS = ["example.com"]
