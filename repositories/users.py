from typing import Any

from psycopg import Connection

from domain.access import Role, User

USER_COLUMNS = "id, email, name, role, is_active"


def _to_user(row: dict[str, Any]) -> User:
    return User(
        id=row["id"],
        email=row["email"],
        name=row["name"],
        role=Role(row["role"]),
        is_active=row["is_active"],
    )


def find_user_by_email(connection: Connection, email: str) -> User | None:
    row = connection.execute(f"SELECT {USER_COLUMNS} FROM users WHERE email = %s", (email,)).fetchone()
    return _to_user(row) if row else None


def find_user_by_id_for_update(connection: Connection, user_id: int) -> User | None:
    row = connection.execute(f"SELECT {USER_COLUMNS} FROM users WHERE id = %s FOR UPDATE", (user_id,)).fetchone()
    return _to_user(row) if row else None


def insert_user(connection: Connection, email: str, name: str, role: Role) -> User:
    row = connection.execute(
        f"INSERT INTO users (email, name, role) VALUES (%s, %s, %s) RETURNING {USER_COLUMNS}",
        (email, name, role.value),
    ).fetchone()
    return _to_user(row)


def record_login(connection: Connection, user_id: int) -> None:
    connection.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (user_id,))


def list_users(connection: Connection) -> list[dict[str, Any]]:
    return connection.execute(f"SELECT {USER_COLUMNS}, last_login_at, created_at FROM users ORDER BY name").fetchall()


def update_user_access(connection: Connection, user_id: int, role: Role, is_active: bool) -> None:
    connection.execute(
        "UPDATE users SET role = %s, is_active = %s WHERE id = %s",
        (role.value, is_active, user_id),
    )


def count_active_admins(connection: Connection) -> int:
    row = connection.execute(
        "SELECT count(*) AS total FROM users WHERE role = %s AND is_active",
        (Role.ADMIN.value,),
    ).fetchone()
    return row["total"]
