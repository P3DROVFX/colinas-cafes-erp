from domain.access import Role

ROLE_LABELS: dict[Role, str] = {
    Role.ADMIN: "Administrador",
    Role.MANAGER: "Gerente",
    Role.PRODUCTION: "Produção",
    Role.SALES: "Comercial",
    Role.FINANCE: "Financeiro",
    Role.VIEWER: "Visitante",
}
