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

USER_TYPES = {
    'adm': 'Administrador',
    'man': 'Gestor',
    'ret': 'Lojista',
    'emp': 'Empregado',
}

print("=== Criar usuário — Retail Analytics ===\n")

full_name = input("Nome completo: ").strip()
username  = input("Username (login): ").strip().lower()
email     = input("E-mail (opcional, Enter para pular): ").strip().lower() or None

print("\nTipos de usuário disponíveis:")
for tid, tname in USER_TYPES.items():
    print(f"  {tid} — {tname}")
user_type_id = input("Tipo de usuário [adm/man/ret/emp]: ").strip().lower()

password = getpass.getpass("\nSenha: ")
confirm  = getpass.getpass("Confirme a senha: ")

if not full_name or not username or not password:
    print("\nErro: nome completo, username e senha são obrigatórios.")
    exit(1)

if user_type_id not in USER_TYPES:
    print(f"\nErro: tipo de usuário inválido. Use: {', '.join(USER_TYPES)}")
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
                INSERT INTO faciais.users (username, full_name, email, password_hash, user_type_id)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING user_id
                """,
                (username, full_name, email, password_hash, user_type_id)
            )
            user_id = cur.fetchone()[0]
        conn.commit()

    print(f"\nUsuário criado com sucesso!")
    print(f"  user_id  : {user_id}")
    print(f"  username : {username}")
    print(f"  tipo     : {user_type_id} — {USER_TYPES[user_type_id]}")

except Exception as e:
    err = str(e).lower()
    if 'unique' in err and 'username' in err:
        print(f"\nErro: já existe um usuário com o username '{username}'.")
    elif 'unique' in err and 'email' in err:
        print(f"\nErro: já existe um usuário com o e-mail '{email}'.")
    else:
        print(f"\nErro ao criar usuário: {e}")
    exit(1)
