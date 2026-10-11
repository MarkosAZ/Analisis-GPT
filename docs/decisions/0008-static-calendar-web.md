# ADR 0008 — Web estática de calendario por petición posterior

Estado: aceptada e implementada; build y despliegue remoto verificados durante la iteración 04.

## Contexto

La planificación reservaba el frontend completo para Fase 7. Después de la
extensión de Fase 2, el usuario pidió ejecutar la página HTML dentro del
repositorio y había autorizado subir el trabajo a GitHub. Esta petición permite
una vista útil de las capacidades existentes, preservando los requisitos de
datos, seguridad y las fases de modelos/evaluación.

## Decisión

Crear HTML/CSS/módulos JS estáticos con calendario, seguimiento e historial por
ciclos. Exportar `public_calendar_v1` desde PostgreSQL con una consulta de solo
lectura consistente. Rechazar campos ajenos al contrato y cadenas incompletas.
No usar la exportación de estado actual como entrada histórica de modelos.

Construir assets por lista explícita y servir un directorio aislado tanto en
desarrollo como en Pages. El workflow publica solo main del repositorio no fork;
únicamente el job de despliegue recibe permisos Pages/OIDC. No hay credenciales
de producción en el navegador ni en los workflows de este incremento.

Mantener el calendario inicial vacío y el ejemplo sintético con activación y
rotulado explícitos. La carga local de JSON no realiza subida ni persistencia.
El HTML original de contexto no participa en la aplicación ni en el build.

## Consecuencias

Se adelanta únicamente la presentación de calendario. Modelos, análisis, paper,
evaluación y sección privada siguen pendientes. Foundation permanece cerrada;
temporadas, resolución de conflictos y operación remota todavía bloquean el
cierre de Fase 2. El snapshot debe actualizarse deliberadamente hasta integrar
la publicación automatizada. Pages requiere habilitación administrativa inicial
y comprobar el despliegue; la configuración del workflow no prueba que esté vivo.
