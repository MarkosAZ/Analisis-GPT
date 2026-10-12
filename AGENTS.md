# Contexto para agentes

Lee `docs/PROJECT_SPEC.md`, `docs/IMPLEMENTATION_STATUS.md` y los ADRs antes de
cambiar arquitectura. Foundation está terminada y Fase 2 está en curso; lee también
`docs/BROWSER_CAPTURE.md` y ADR 0007. El usuario solicitó un provider mediante
extensión manual y después una web HTML ejecutable. Lee también `docs/WEB.md` y
ADR 0008: existe una vista estática de calendario, sin adelantar modelos, paper
ni la sección privada. Continúa cerrando Fase 2.

La petición posterior exige automatización desde la web: consulta
`docs/AUTOMATIC_SCANNING.md` y ADRs 0009/0010. La extensión 0.4 incluye conectores
de navegador para SofaScore, Betano, Apuesta Total y Flashscore, basados en los
formatos de la referencia indicada por el usuario; conserva perfiles DOM y modo
manual. Te Apuesto sigue sin conector. No confundas pruebas con fixtures con
aceptación de fuentes reales: esta última sigue pendiente en Chrome/Edge local.
El acceso cloud no es un requisito para ejecutar los conectores en el navegador
del usuario. No presentes el botón que abre portadas como extracción.

Trabaja en el checkout actual. Una tarea cloud ya está aislada: no crees otro
worktree salvo petición explícita. Preserva cambios existentes del usuario.

Invariantes: `available_at <= decision_time`; UUID internos; historial por
`event_cycle`; RAW inmutable; políticas y modelos prospectivos; holdout protegido;
distinción favored/value; worker público sin acceso a `private_betting`.
No incorpores el HTML original ni datos privados a Git, paquetes, logs o artifacts.

Los providers retornan RAW y se normaliza después de persistirlo. No acoples el
dominio a APIs concretas ni evadas protecciones. Las fuentes reales requieren
acceso autorizado. Las apuestas reales pertenecen al futuro repositorio privado.

Instala con `uv sync --frozen`. Valida con `ruff check`, `ruff format --check`,
`mypy`, `pytest` y el comprobador público; consulta `DEVELOPMENT.md`. Los cambios
SQL requieren PostgreSQL real y `TEST_DATABASE_URL` a una base desechable. No
presentes tests omitidos como aprobados. No edites migraciones ya aplicadas.

Documenta decisiones técnicas nuevas, limitaciones y el estado de requisitos.
La fuente del precio paper y los thresholds NO BET siguen pendientes; no actives
versiones utilizando resultados futuros ni interpretes los fixtures como una
estrategia validada.
