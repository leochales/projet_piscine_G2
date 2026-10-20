import os

# Les tests ne touchent pas à la base : des identifiants factices suffisent
# (en CI, il n'y a pas de .env)
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_DB", "test")
