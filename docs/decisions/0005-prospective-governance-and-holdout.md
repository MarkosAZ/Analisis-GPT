# ADR 0005 — Vigencia prospectiva y holdout protegido

Estado: aceptada.

## Contexto

Seleccionar thresholds/modelos después de observar resultados y atribuirles decisiones pasadas produce un historial artificial. Un holdout no está protegido si el mismo worker habitual puede desbloquearlo.

## Decisión

Registrar deployments y políticas con vigencia, hashes y comienzo de track record. Las versiones nuevas empiezan prospectivamente. Los experimentos mantienen intento, configuración, dataset y ventana. Restringir acceso normal a holdout y reservar el desbloqueo a una futura acción manual, privilegiada y auditada.

## Consecuencias

Los permisos generales sobre `ml` se reducen cuando permitirían saltarse la protección. La administración de migraciones es distinta del runtime. El desbloqueo no garantiza significancia ni permite volver a presentar una ventana ya explorada como prueba intacta. Log-loss y calibración prevalecen sobre una selección basada únicamente en ROI.
