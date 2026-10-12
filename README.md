# Analisis-GPT

Fundación de un sistema de análisis deportivo **prepartido** para fútbol, básquet
y béisbol. Predicciones, paper betting y apuestas reales tienen dominios y permisos
separados. La información histórica se consulta según lo que estaba disponible en
`decision_time`.

Foundation está completada. **Fase 2 está en curso**: extensión local para Chrome/
Edge, capturas manuales revisadas, importación RAW, calendario, mappings, ciclos y
tracking. Incluye una **web HTML estática** con calendario, seguimiento e historial
de ciclos. La extensión 0.4 incluye conectores para SofaScore, Betano Perú,
Apuesta Total y Flashscore, activables sin escribir JSON: inicia el escaneo desde
la web y consulta capturas y diagnóstico. Te Apuesto sigue pendiente. Los
conectores están probados con fixtures; falta aceptación con fuentes reales en
el navegador del usuario. No hay predicciones.

Para usar la extensión, sigue la [guía de instalación](extension/README.md).
El [recorrido de importación](docs/BROWSER_CAPTURE.md) explica cómo conectar las
capturas con PostgreSQL sin entregar credenciales al navegador.
La [guía de escaneo automático](docs/AUTOMATIC_SCANNING.md) explica el botón web,
los permisos por sitio, conectores incluidos, perfiles opcionales y diagnóstico.

## Empezar

```bash
uv sync --frozen
uv run pytest tests/unit
uv run ruff check .
uv run mypy
```

Para ejecutar la página desde este repositorio:

```bash
uv run python scripts/serve_site.py --port 8000
```

El servidor local construye y sirve únicamente archivos públicos. La página empieza
sin partidos publicados; **Explorar ejemplo** abre datos ficticios identificados.
Consulta [la guía web](docs/WEB.md) para cargar datos, generar el sitio y activar
GitHub Pages con el workflow incluido. No abras `index.html` mediante `file://`:
los módulos y JSON necesitan HTTP.

Consulta [DEVELOPMENT.md](DEVELOPMENT.md) para iniciar PostgreSQL desechable,
validar migraciones y ejecutar también la suite de integración. No se requieren
credenciales de Neon, R2 o proveedores para Foundation.

## Contexto del proyecto

- [Especificación consolidada](docs/PROJECT_SPEC.md): decisiones vigentes y fases.
- [Estado de implementación](docs/IMPLEMENTATION_STATUS.md): cubierto y pendiente.
- [Arquitectura](ARCHITECTURE.md) y [modelo de datos](DATA_MODEL.md).
- [Point-in-time](POINT_IN_TIME.md), [seguridad](SECURITY.md) y
  [gobernanza de modelos](MODEL_GOVERNANCE.md).
- [Decisiones arquitectónicas](docs/decisions/).

## Estructura

```text
src/sports_analysis/
  domain/       # invariantes temporales, eventos, mercados y gobernanza
  providers/    # contratos independientes de fuentes concretas
  storage/      # RAW inmutable y backend local
  db/           # runner de migraciones con hashes y transacciones
migrations/     # esquemas, constraints, semillas y permisos PostgreSQL
extension/      # panel lateral MV3, selección explícita y exportación JSON
index.html      # entrada de la web estática
web/            # interfaz, contrato público y ejemplo sintético
config/         # políticas versionadas, pendientes de activación
tests/          # dominio e integración con PostgreSQL real
docs/           # especificación, estado y ADRs
scripts/        # controles del repositorio público
.github/        # CI sin secretos de producción
```

El siguiente hito es cerrar **Fase 2**: temporadas, resolución de conflictos,
fuente/recepción autorizada y workflows operativos con persistencia real. La
extensión ya conserva cuotas RAW; benchmarks, modelos, evaluación y las vistas
avanzadas de Pages siguen en sus fases. El estado y las limitaciones están en la
matriz de implementación.
