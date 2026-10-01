import os

from hypothesis import settings

settings.register_profile("ci", derandomize=True, deadline=None, max_examples=100, print_blob=True)
settings.register_profile("dev", deadline=None, max_examples=50)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))
