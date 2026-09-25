import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://statusforge:statusforge@localhost:5432/statusforge")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough-for-validation")
