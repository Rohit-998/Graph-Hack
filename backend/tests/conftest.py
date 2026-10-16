import os

# Tests are deterministic and must not spend LLM quota. Set before firebreak.config loads
# (python-dotenv does not override variables that are already set).
os.environ["LLM_PROVIDER"] = "none"
