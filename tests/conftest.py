import os

# Importing lead_agent builds the agent, which needs a project. Tests never call the model.
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")
