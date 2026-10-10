# ADR 0001 — Foundation modular y avance por fases

Estado: aceptada.

## Contexto

El proyecto incluye datos deportivos, odds, modelos, evaluación y un sitio público. Implementarlo todo antes de validar tiempo, identidad y permisos multiplicaría los errores difíciles de corregir.

## Decisión

Usar un monolito Python modular, PostgreSQL externo y object storage, con GitHub Actions como ejecutor y Pages como frontend estático futuro. Completar Foundation antes de calendario/tracking; después odds, modelos estadísticos, evaluación, ML y Pages. No se añaden microservicios ni una base de datos separada por deporte.

## Consecuencias

Foundation implementa contratos, migraciones, permisos y tests, pero no promete proveedores o modelos operativos. La próxima iteración está delimitada por calendario/providers/tracking. El historial se conserva como especificación consolidada, sin publicar su archivo HTML.
