"""
Cria um usuário na tabela faciais.users.
Uso: python criar_usuario.py
"""
import os
import getpass
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash
import db

load_dotenv()

print("=== Criar usuário — Retail Analytics ===\n")

full_name = input("Nome completo: ").strip()
email     = input("E-mail: ").strip().lower()
password  = getpass.getpass("Senha: ")
confirm   = getpass.getpass("Confirme a senha: ")

if not full_name or not email or not password:
    print("\nErro: todos os campos são obrigatórios.")
    exit(1)

if password != confirm:
    print("\nErro: as senhas não coincidem.")
    exit(1)

password_hash = generate_password_hash(password)

try:
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO faciais.users (full_name, email, password_hash)
                VALUES (%s, %s, %s)
                RETURNING user_id
                """,
                (full_name, email, password_hash)
            )
            user_id = cur.fetchone()[0]
        conn.commit()

    print(f"\nUsuário criado com sucesso! (user_id={user_id})")

except Exception as e:
    if 'unique' in str(e).lower():
        print(f"\nErro: já existe um usuário com o e-mail '{email}'.")
    else:
        print(f"\nErro ao criar usuário: {e}")
    exit(1)
