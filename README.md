# JJA TECH — versão inicial funcional

Aplicação Flask com login, inventário por patrimônio, contagem automática, empréstimos por professor/turma, devoluções parciais por patrimônio, registro de condição, auditoria e exportação CSV.

## Rodar localmente

1. Instale Python 3.11+ e crie um ambiente virtual: `python -m venv .venv`.
2. Ative-o (`source .venv/bin/activate` no macOS/Linux; `.venv\\Scripts\\activate` no Windows).
3. Instale: `pip install -r requirements.txt`.
4. Defina `SECRET_KEY` e `ADMIN_PASSWORD` como variáveis de ambiente; a senha deve ter no mínimo 12 caracteres. Para desenvolvimento local, pode deixar `DATABASE_URL` sem definir, usando SQLite. **Não use SQLite em produção no Render**.
5. Execute `flask --app app init-db` e depois `flask --app app run`.
6. Acesse `http://127.0.0.1:5000` e entre com `admin` e a senha configurada.

## Publicar no Render

1. Crie um repositório GitHub **privado** com estes arquivos, sem segredos.
2. Crie um banco PostgreSQL persistente (Render Postgres ou Supabase). Copie a URL de conexão. No Supabase, verifique a URL e o modo de conexão apropriado para seu projeto.
3. No Render, crie um **Web Service** ligado ao repositório, com runtime Python.
4. Build command: `pip install -r requirements.txt`
5. Start command: `gunicorn --bind 0.0.0.0:$PORT app:app`
6. Configure as variáveis de ambiente `DATABASE_URL`, `SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `COOKIE_SECURE=1`.
7. Inicialize o banco **uma vez**, usando um shell com as mesmas variáveis: `flask --app app init-db`. Se o plano não disponibilizar shell, execute esse comando em uma máquina local apontando para o PostgreSQL remoto com conexão segura. **Não coloque init-db no start command**.
8. Abra a URL HTTPS fornecida pelo Render, faça login, cadastre alguns equipamentos e teste empréstimo/devolução.
9. Configure backups periódicos do PostgreSQL e teste a restauração.

## Regras

- Um patrimônio representa um equipamento físico; portanto a quantidade é a contagem dos patrimônios selecionados.
- Equipamentos emprestados não podem ser novamente retirados.
- A devolução pode ser parcial, marcando os itens individualmente.
- Itens devolvidos como danificados ficam indisponíveis.
- `admin` cadastra equipamentos e registra movimentações. O modelo prevê `operator` (movimentações) e `viewer` (consulta), mas **a criação e administração desses usuários ainda exige ferramenta administrativa ou desenvolvimento adicional**.
- O relatório CSV contém histórico completo; o painel exibe os 60 empréstimos mais recentes.

## Limitações antes de produção

Esta é uma **primeira versão**, não uma solução final auditada. O campo de previsão de devolução e os horários da interface usam UTC (ajustar para America/Sao_Paulo). Ainda faltam: gestão de usuários pela interface, redefinição de senha, rate limiting de login, migrations, paginação e filtros, logs/monitoramento, tratamento de incidentes, testes de concorrência em PostgreSQL, política de retenção/LGPD, termo de responsabilidade e rotinas formais de backup. Antes do uso real, valide com a gestão da escola e as regras de TI/SEDUC aplicáveis. Não use dados pessoais reais em testes públicos.
