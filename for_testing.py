from passlib.context import CryptContext

# Configuration de passlib pour utiliser bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str):
    return pwd_context.hash(password)

# Exemple d'utilisation :
nouveau_hash = get_password_hash("Admin2026")
print(nouveau_hash)