# ADR 0009 — Escaneo automático iniciado desde el sitio

Estado: aceptada; motor implementado, lectores reales pendientes de verificación.

## Contexto

El usuario corrigió el alcance manual de ADR 0007: la extensión debe abrir las
páginas necesarias y escanear desde la web. Eligió SofaScore, Betano Perú, Apuesta
Total, Te Apuesto y Flashscore Perú. Esto reemplaza la restricción anterior de
captura exclusivamente manual, sin cambiar seguridad, separación privada ni PIT.

## Decisión

Mantener la extensión MV3 e introducir un puente fijo al sitio del proyecto,
permisos opcionales por host y lectores DOM declarativos versionados. El service
worker ejecuta una cola secuencial, conserva estado/capturas en sesión y falla
de forma explícita ante interrupciones, redirecciones, ambigüedades o bloqueos.
No ejecutar código remoto ni recibir URLs arbitrarias desde Pages.

Conservar el modo manual v1. Las observaciones automáticas usan v2, con método,
lector, scan y perfil/hash auditables. Importar lotes con validación completa,
recepción SQL confiable, RAW previo a normalización y reintentos idempotentes.
No añadir modelos ni activar odds/paper antes de sus fases.

## Consecuencias y límites comprobados

La apertura de cinco portadas está implementada como navegación, separada del
escaneo con lector válido. La red cloud denegó las cinco inspecciones antes de
obtener contenido; no se inventaron selectores ni se afirmó soporte real de cuotas.
La automatización se valida con fixtures. Los perfiles de producción, navegación
entre eventos y aceptación real de Chrome/Edge siguen pendientes de acceso y
verificación. El borrador de red incluye exactamente los cinco dominios pedidos;
guardarlo no cambia la instancia en ejecución.

La extensión no es un worker de GitHub Actions ni un backend para Pages. Su
recepción remota autenticada y publicación de nuevos snapshots siguen pendientes.
