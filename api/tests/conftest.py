import os

# Les tests ne touchent pas à la base : des identifiants factices suffisent
# (en CI, il n'y a pas de .env)
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("PRIX_KWH_EUR", "0.14")
# Pas de seeding au démarrage de l'app des tests (TestClient), même si le .env le
# configure : une variable d'environnement passe avant le .env
os.environ["SEED_PASSWORD"] = ""
