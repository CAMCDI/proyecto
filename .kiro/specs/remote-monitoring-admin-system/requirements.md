# Requirements Document

## Introduction

Este documento especifica los requisitos para un Sistema Completo de Monitoreo y Administración Remota cliente-servidor diseñado para prácticas universitarias de redes e instrumentación. El sistema permite a un servidor administrador monitorear y controlar hasta 3 clientes Linux en una red LAN con comunicación segura, incluyendo streaming de pantalla, transferencia de archivos, chat bidireccional, control de dispositivos de entrada, administración de red y gestión de energía.

## Glossary

- **Server**: Aplicación de administración que gestiona y controla los clientes remotos
- **Client**: Agente instalado en las máquinas a ser monitoreadas y controladas
- **Helper**: Proceso privilegiado auxiliar que ejecuta operaciones que requieren permisos de superusuario
- **Session**: Periodo de tiempo durante el cual el servidor está conectado y controlando un cliente
- **Remote_Control_Protocol**: Protocolo de comunicación basado en JSON sobre TCP/TLS para intercambiar comandos y datos
- **Screen_Stream**: Flujo continuo de capturas de pantalla comprimidas enviadas desde el cliente al servidor
- **Input_Device**: Dispositivo de entrada del usuario (teclado o mouse) controlado por X11/Wayland
- **Authentication_Token**: Credencial hasheada utilizada para autenticar la conexión servidor-cliente
- **Watchdog**: Mecanismo de seguridad que desbloquea automáticamente el cliente si pierde conexión con el servidor
- **Action_Log**: Registro auditable de todas las operaciones realizadas por el servidor sobre los clientes
- **Client_Panel**: Interfaz que muestra el estado y métricas de los 3 clientes conectados
- **Domain_Blocklist**: Lista de dominios web cuyo acceso está bloqueado en el cliente
- **SHA256_Checksum**: Hash criptográfico utilizado para verificar la integridad de archivos transferidos
- **ICMP_Echo**: Paquete ping utilizado para verificar conectividad de red
- **TLS_Connection**: Conexión TCP cifrada utilizando certificados autofirmados
- **Privilege_Separation**: Arquitectura donde la UI y el helper privilegiado operan en procesos separados

## Requirements

### Requirement 1: Streaming de Pantalla en Tiempo Real

**User Story:** Como administrador del servidor, quiero observar la pantalla del cliente remoto en tiempo real, para poder supervisar la actividad del usuario y diagnosticar problemas visualmente.

#### Acceptance Criteria

1. WHEN el administrador selecciona un cliente conectado, THE Server SHALL mostrar el Screen_Stream del cliente en una ventana dedicada
2. WHEN se está transmitiendo pantalla, THE Client SHALL capturar frames a 5-10 FPS y comprimirlos en formato JPEG con calidad ajustable (50-90%)
3. WHEN un frame es capturado, THE Client SHALL enviar el frame comprimido al Server a través del Remote_Control_Protocol
4. THE Server SHALL permitir ajustar la resolución del Screen_Stream entre 640x480, 800x600, 1024x768 y resolución nativa
5. WHEN la resolución es cambiada, THE Client SHALL escalar las capturas de pantalla a la resolución solicitada antes de comprimir
6. WHILE el Screen_Stream está activo, THE Server SHALL mostrar el framerate actual y el ancho de banda utilizado
7. WHEN el cliente es desconectado, THE Server SHALL detener el Screen_Stream y mostrar un mensaje de "Desconectado"
8. THE Client SHALL utilizar la librería mss para captura de pantalla en sistemas X11
9. WHEN ocurre un error de captura, THE Client SHALL registrar el error en el Action_Log local y continuar intentando capturar

### Requirement 2: Transferencia Bidireccional de Archivos

**User Story:** Como administrador del servidor, quiero transferir archivos entre el servidor y los clientes en ambas direcciones, para poder distribuir materiales o recoger trabajos de forma segura y verificable.

#### Acceptance Criteria

1. THE Server SHALL permitir seleccionar un archivo local y enviarlo a un Client específico
2. THE Client SHALL permitir seleccionar un archivo local y enviarlo al Server
3. WHEN un archivo es seleccionado para transferencia, THE emisor SHALL calcular el SHA256_Checksum del archivo completo
4. WHEN inicia una transferencia, THE emisor SHALL dividir el archivo en bloques de 64KB y enviarlos secuencialmente
5. WHEN cada bloque es recibido, THE receptor SHALL escribir el bloque en el archivo de destino y confirmar la recepción
6. WHILE una transferencia está en progreso, THE emisor SHALL mostrar una barra de progreso con porcentaje, velocidad y tiempo restante estimado
7. WHEN todos los bloques son recibidos, THE receptor SHALL calcular el SHA256_Checksum del archivo recibido
8. IF el checksum recibido coincide con el checksum calculado, THEN THE receptor SHALL confirmar transferencia exitosa
9. IF el checksum no coincide, THEN THE receptor SHALL rechazar el archivo, eliminarlo y notificar al emisor del error
10. WHEN una transferencia es completada o falla, THE Server y THE Client SHALL registrar el evento en sus respectivos Action_Log con timestamp, nombres de archivo y resultado

### Requirement 3: Chat Bidireccional en Tiempo Real

**User Story:** Como administrador del servidor, quiero comunicarme mediante mensajes de texto con los clientes conectados, para poder dar instrucciones, hacer preguntas o coordinar actividades sin interrumpir su trabajo.

#### Acceptance Criteria

1. THE Server SHALL mostrar una interfaz de chat para cada Client conectado con área de mensajes e input de texto
2. THE Client SHALL mostrar una ventana de chat con área de mensajes e input de texto
3. WHEN el administrador envía un mensaje, THE Server SHALL transmitir el mensaje al Client seleccionado a través del Remote_Control_Protocol
4. WHEN el usuario del cliente envía un mensaje, THE Client SHALL transmitir el mensaje al Server a través del Remote_Control_Protocol
5. WHEN un mensaje es recibido, THE receptor SHALL mostrar el mensaje en el área de chat con formato "[HH:MM:SS] Emisor: mensaje"
6. THE Server y THE Client SHALL mantener un historial de los últimos 200 mensajes en memoria durante la Session
7. WHEN un mensaje es enviado o recibido, THE interfaz de chat SHALL hacer scroll automático al mensaje más reciente
8. THE Server SHALL identificar mensajes propios con el prefijo "Servidor:" y mensajes del cliente con el hostname del Client
9. THE Client SHALL identificar mensajes propios con el prefijo "Cliente:" y mensajes del servidor con "Servidor:"
10. WHEN se envía un mensaje de más de 1000 caracteres, THE emisor SHALL rechazar el envío y mostrar error de longitud máxima

### Requirement 4: Panel de Estado de Múltiples Clientes

**User Story:** Como administrador del servidor, quiero ver el estado, métricas y una vista previa de todos los clientes conectados simultáneamente, para poder identificar rápidamente qué cliente requiere atención o cual deseo controlar.

#### Acceptance Criteria

1. THE Server SHALL mostrar un Client_Panel con exactamente 3 slots para clientes
2. WHEN un Client se conecta, THE Server SHALL asignar el Client a un slot disponible del Client_Panel
3. FOR cada Client conectado, THE Server SHALL mostrar hostname, dirección IP, sistema operativo y versión
4. FOR cada Client conectado, THE Server SHALL mostrar el estado de conexión como "Conectado" en color verde o "Desconectado" en color gris
5. WHILE un Client está conectado, THE Server SHALL solicitar y mostrar el porcentaje de uso de CPU y RAM actualizados cada 2 segundos
6. WHILE un Client está conectado, THE Server SHALL solicitar y mostrar una miniatura de pantalla de 160x120 píxeles actualizada cada 5 segundos
7. WHEN el administrador hace clic en un slot de cliente conectado, THE Server SHALL seleccionar ese Client como el cliente activo para operaciones de control
8. THE Server SHALL resaltar visualmente el slot del Client actualmente seleccionado con un borde de color distintivo
9. WHEN un Client se desconecta, THE Server SHALL actualizar su slot a estado "Desconectado" y detener las actualizaciones de métricas
10. THE Server SHALL utilizar la librería psutil en el Client para obtener las métricas de CPU y RAM

### Requirement 5: Registro de Auditoría de Acciones

**User Story:** Como administrador del servidor y como usuario del cliente, quiero ver un registro completo de todas las acciones realizadas, para mantener transparencia, auditar actividades y diagnosticar problemas.

#### Acceptance Criteria

1. THE Server SHALL mantener un Action_Log visible en la interfaz que muestre todas las acciones realizadas en orden cronológico
2. WHEN ocurre una acción, THE Server SHALL agregar una entrada al Action_Log con formato "[YYYY-MM-DD HH:MM:SS] [Cliente: hostname] [Acción] Descripción"
3. THE Server SHALL registrar los siguientes eventos: conexión de cliente, desconexión, selección de cliente, inicio/fin de Screen_Stream, envío/recepción de archivo, bloqueo/desbloqueo de input, apagado remoto, modificación de Domain_Blocklist, modificación de respuesta ICMP_Echo
4. THE Server SHALL permitir filtrar el Action_Log por cliente específico o por tipo de acción
5. THE Server SHALL permitir exportar el Action_Log completo a un archivo de texto con timestamp en el nombre
6. THE Client SHALL mostrar una ventana semi-transparente con el Action_Log de las acciones que el Server está realizando sobre él
7. WHEN el Server ejecuta una acción sobre el Client, THE Client SHALL agregar una entrada a su Action_Log local con formato "[HH:MM:SS] Servidor ejecutó: [Acción]"
8. THE Client SHALL mantener visible su ventana de Action_Log en primer plano durante toda la Session activa
9. THE Client SHALL registrar eventos locales: conexión establecida, desconexión, recepción de comando, inicio/fin de captura de pantalla, bloqueo/desbloqueo de Input_Device, modificación de Domain_Blocklist, modificación de ICMP_Echo
10. WHEN el Action_Log del Client supera 100 entradas, THE Client SHALL mantener solo las 100 entradas más recientes en la ventana visible

### Requirement 6: Bloqueo Remoto de Dispositivos de Entrada

**User Story:** Como administrador del servidor, quiero bloquear el teclado y mouse del cliente remoto, para poder tomar control de la sesión, evitar interrupciones durante demostraciones o asegurar que el usuario no interfiera durante mantenimiento.

#### Acceptance Criteria

1. THE Server SHALL proporcionar un botón "Bloquear Teclado/Mouse" en la interfaz de control del Client seleccionado
2. WHEN el administrador hace clic en "Bloquear Teclado/Mouse", THE Server SHALL enviar comando de bloqueo al Client a través del Remote_Control_Protocol
3. WHEN el Client recibe comando de bloqueo, THE Client SHALL ejecutar `xinput disable` para cada Input_Device de tipo teclado y mouse en sistemas X11
4. WHEN los Input_Device son bloqueados, THE Client SHALL mostrar una notificación en pantalla "Teclado y mouse bloqueados por el administrador"
5. WHEN el bloqueo es aplicado, THE Client SHALL registrar el evento en su Action_Log con timestamp
6. WHEN el bloqueo es aplicado exitosamente, THE Client SHALL enviar confirmación al Server
7. WHEN el Server recibe confirmación de bloqueo, THE Server SHALL registrar el evento en el Action_Log del servidor
8. WHILE los Input_Device están bloqueados, THE Client SHALL ignorar cualquier intento del usuario local de usar teclado o mouse
9. THE Client SHALL identificar los IDs de Input_Device ejecutando `xinput list` y parseando la salida al inicio
10. IF el sistema usa Wayland en lugar de X11, THEN THE Client SHALL registrar advertencia en Action_Log indicando que bloqueo de input no está soportado en Wayland

### Requirement 7: Desbloqueo Remoto de Dispositivos de Entrada

**User Story:** Como administrador del servidor, quiero desbloquear el teclado y mouse del cliente remoto, para permitir que el usuario recupere el control de su máquina cuando haya terminado el mantenimiento o control remoto.

#### Acceptance Criteria

1. THE Server SHALL proporcionar un botón "Desbloquear Teclado/Mouse" en la interfaz de control del Client seleccionado
2. WHEN el administrador hace clic en "Desbloquear Teclado/Mouse", THE Server SHALL enviar comando de desbloqueo al Client a través del Remote_Control_Protocol
3. WHEN el Client recibe comando de desbloqueo, THE Client SHALL ejecutar `xinput enable` para cada Input_Device de tipo teclado y mouse previamente bloqueado
4. WHEN los Input_Device son desbloqueados, THE Client SHALL ocultar la notificación de bloqueo y mostrar "Teclado y mouse desbloqueados"
5. WHEN el desbloqueo es aplicado, THE Client SHALL registrar el evento en su Action_Log con timestamp
6. WHEN el desbloqueo es aplicado exitosamente, THE Client SHALL enviar confirmación al Server
7. WHEN el Server recibe confirmación de desbloqueo, THE Server SHALL registrar el evento en el Action_Log del servidor
8. WHEN los Input_Device son desbloqueados, THE usuario del Client SHALL poder utilizar teclado y mouse normalmente
9. WHEN el Client detecta desconexión del Server, THE Watchdog SHALL desbloquear automáticamente todos los Input_Device después de 10 segundos sin comunicación
10. THE Client SHALL implementar una combinación de teclas de emergencia (Ctrl+Alt+Shift+U) que desbloquea los Input_Device localmente en caso de emergencia

### Requirement 8: Apagado Remoto de Cliente

**User Story:** Como administrador del servidor, quiero apagar de forma segura los clientes remotos, para poder finalizar la sesión de laboratorio, aplicar políticas de ahorro energético o realizar mantenimiento programado.

#### Acceptance Criteria

1. THE Server SHALL proporcionar un botón "Apagar Cliente" en la interfaz de control del Client seleccionado
2. WHEN el administrador hace clic en "Apagar Cliente", THE Server SHALL mostrar un diálogo de confirmación con advertencia "¿Está seguro de apagar [hostname]? Esta acción no se puede deshacer."
3. WHEN el administrador confirma el apagado, THE Server SHALL enviar comando de apagado al Client a través del Remote_Control_Protocol
4. WHEN el Client recibe comando de apagado, THE Client SHALL mostrar una ventana modal en pantalla completa con cuenta regresiva "El sistema se apagará en 30 segundos"
5. WHILE la cuenta regresiva está activa, THE Client SHALL actualizar el contador cada segundo mostrando el tiempo restante
6. WHEN la cuenta regresiva llega a 0, THE Client SHALL ejecutar el Helper privilegiado que invoca `systemctl poweroff`
7. THE Helper SHALL estar configurado en sudoers o polkit para permitir únicamente el comando `systemctl poweroff` sin solicitar contraseña
8. WHEN el comando de apagado es enviado, THE Client SHALL registrar el evento en Action_Log antes de iniciar la cuenta regresiva
9. WHEN el comando de apagado es enviado, THE Server SHALL registrar el evento en su Action_Log incluyendo hostname y timestamp
10. WHEN el Client comienza el proceso de apagado, THE Server SHALL detectar la desconexión y actualizar el estado del Client_Panel a "Desconectado"

### Requirement 9: Control de Acceso a Sitios Web

**User Story:** Como administrador del servidor, quiero bloquear el acceso a sitios web específicos en los clientes, para poder aplicar políticas de uso aceptable, evitar distracciones durante exámenes o proteger contra sitios maliciosos.

#### Acceptance Criteria

1. THE Server SHALL proporcionar una interfaz "Bloqueo de Sitios Web" con campo de texto y botones "Agregar Dominio" y "Quitar Dominio"
2. WHEN el administrador ingresa un dominio y hace clic en "Agregar Dominio", THE Server SHALL validar que el dominio tenga formato válido (por ejemplo, "example.com" o "www.example.com")
3. WHEN un dominio es validado, THE Server SHALL enviar comando de bloqueo con el dominio al Client seleccionado a través del Remote_Control_Protocol
4. WHEN el Client recibe comando de agregar dominio a Domain_Blocklist, THE Client SHALL invocar el Helper privilegiado para agregar entrada al archivo /etc/hosts
5. THE Helper SHALL agregar línea "127.0.0.1 [dominio]" al archivo /etc/hosts para cada dominio bloqueado
6. WHEN un dominio es agregado a /etc/hosts, THE Client SHALL registrar el evento en Action_Log con el dominio bloqueado
7. THE Server SHALL mantener y mostrar la Domain_Blocklist actual del Client seleccionado en la interfaz
8. WHEN el administrador selecciona un dominio de la Domain_Blocklist y hace clic en "Quitar Dominio", THE Server SHALL enviar comando de desbloqueo al Client
9. WHEN el Client recibe comando de quitar dominio, THE Helper SHALL eliminar la línea correspondiente del archivo /etc/hosts
10. WHEN un dominio es removido de /etc/hosts, THE Client SHALL registrar el evento en Action_Log y enviar confirmación al Server con la Domain_Blocklist actualizada

### Requirement 10: Control de Respuesta ICMP

**User Story:** Como administrador del servidor, quiero activar o desactivar la respuesta a pings (ICMP echo requests) en los clientes, para poder simular diferentes escenarios de red, realizar pruebas de diagnóstico de conectividad o aplicar políticas de seguridad de red.

#### Acceptance Criteria

1. THE Server SHALL proporcionar botones "Denegar Ping" y "Permitir Ping" en la interfaz de control de red del Client seleccionado
2. WHEN el administrador hace clic en "Denegar Ping", THE Server SHALL enviar comando de deshabilitar ICMP_Echo al Client
3. WHEN el Client recibe comando de denegar ping, THE Helper SHALL ejecutar `sysctl -w net.ipv4.icmp_echo_ignore_all=1` para desactivar respuestas ICMP echo
4. WHEN la respuesta ICMP_Echo es deshabilitada, THE Client SHALL registrar el evento en Action_Log con timestamp
5. WHEN la configuración es aplicada exitosamente, THE Client SHALL enviar confirmación al Server indicando "Ping denegado"
6. WHEN el Server recibe confirmación, THE Server SHALL actualizar la interfaz mostrando estado "Ping: Denegado" y registrar el evento en Action_Log
7. WHEN el administrador hace clic en "Permitir Ping", THE Server SHALL enviar comando de habilitar ICMP_Echo al Client
8. WHEN el Client recibe comando de permitir ping, THE Helper SHALL ejecutar `sysctl -w net.ipv4.icmp_echo_ignore_all=0` para reactivar respuestas ICMP echo
9. WHEN la respuesta ICMP_Echo es habilitada, THE Client SHALL registrar el evento en Action_Log con timestamp y enviar confirmación al Server
10. THE Helper SHALL requerir privilegios elevados para modificar la configuración sysctl y estar configurado en sudoers o polkit específicamente para este comando

### Requirement 11: Autenticación y Comunicación Segura

**User Story:** Como administrador del servidor y desarrollador del sistema, quiero que todas las comunicaciones entre servidor y clientes estén cifradas y autenticadas, para proteger la confidencialidad e integridad de los datos transmitidos y prevenir accesos no autorizados.

#### Acceptance Criteria

1. THE Server y THE Client SHALL establecer TLS_Connection utilizando certificados autofirmados X.509
2. WHEN el sistema es instalado por primera vez, THE script de instalación SHALL generar un par de certificados (servidor y cliente) válidos por 365 días
3. THE Server SHALL almacenar el certificado del servidor y las claves privadas en archivos con permisos 600 (lectura/escritura solo para el propietario)
4. WHEN un Client intenta conectarse, THE Server SHALL verificar el certificado del cliente contra una lista de certificados autorizados
5. WHEN un Client intenta conectarse, THE Client SHALL enviar un Authentication_Token derivado de una contraseña mediante argon2id con sal única
6. THE Server SHALL validar el Authentication_Token contra un hash almacenado antes de aceptar la conexión
7. IF el certificado o el Authentication_Token son inválidos, THEN THE Server SHALL rechazar la conexión y registrar el intento fallido en Action_Log
8. WHEN la autenticación es exitosa, THE Server SHALL establecer la TLS_Connection y comenzar la Session
9. THE Server y THE Client SHALL mantener las credenciales (contraseñas, tokens) en archivos de configuración separados con permisos 600
10. THE Remote_Control_Protocol SHALL transmitir todos los mensajes, comandos y datos sobre la TLS_Connection establecida

### Requirement 12: Validación y Sanitización de Entradas

**User Story:** Como desarrollador del sistema, quiero validar y sanitizar todas las entradas de usuario y datos recibidos de la red, para prevenir inyección de comandos, desbordamiento de búfer, path traversal y otras vulnerabilidades de seguridad.

#### Acceptance Criteria

1. THE Server y THE Client SHALL definir una lista blanca de comandos permitidos en el Remote_Control_Protocol (por ejemplo: "screen_start", "screen_stop", "file_send", "chat_message", "input_lock", etc.)
2. WHEN se recibe un mensaje del Remote_Control_Protocol, THE receptor SHALL verificar que el tipo de comando esté en la lista blanca antes de procesarlo
3. IF un comando no está en la lista blanca, THEN THE receptor SHALL rechazar el mensaje, registrar el intento en Action_Log y cerrar la conexión
4. WHEN se recibe un nombre de archivo, THE receptor SHALL validar que el nombre no contenga secuencias de path traversal (por ejemplo: "..", "/", caracteres nulos)
5. WHEN se recibe un nombre de dominio, THE Server SHALL validar el formato usando expresión regular que permita solo caracteres alfanuméricos, guiones y puntos
6. WHEN se recibe un mensaje de chat, THE receptor SHALL limitar la longitud a 1000 caracteres y escapar caracteres especiales HTML antes de mostrar
7. THE Server y THE Client SHALL limitar el tamaño máximo de mensajes del Remote_Control_Protocol a 10MB para prevenir ataques de memoria
8. WHEN se recibe un path de archivo, THE receptor SHALL resolver el path absoluto y verificar que esté dentro de directorios permitidos antes de acceder
9. THE Client SHALL rechazar cualquier comando que intente ejecutar shell arbitrario o acceder a comandos fuera del conjunto predefinido
10. THE Server SHALL implementar rate limiting permitiendo máximo 100 mensajes por segundo por cliente para prevenir flooding

### Requirement 13: Principio de Menor Privilegio y Separación de Privilegios

**User Story:** Como desarrollador del sistema, quiero separar las operaciones privilegiadas en un proceso auxiliar mínimo, para reducir la superficie de ataque y limitar el daño potencial si el proceso principal es comprometido.

#### Acceptance Criteria

1. THE Client SHALL ejecutar la aplicación principal (UI y lógica de red) con privilegios de usuario normal sin sudo
2. THE Client SHALL comunicarse con el Helper mediante un socket local UNIX o pipe con permisos restrictivos 600
3. THE Helper SHALL ser un proceso separado con privilegios elevados que ejecuta únicamente operaciones específicas que requieren sudo
4. THE Helper SHALL aceptar únicamente comandos de una lista blanca predefinida: "shutdown", "block_domain", "unblock_domain", "disable_ping", "enable_ping"
5. WHEN el Helper recibe un comando, THE Helper SHALL validar el formato y parámetros antes de ejecutar cualquier operación privilegiada
6. THE Helper SHALL registrar cada comando recibido y ejecutado en un log de auditoría separado accesible solo por root
7. THE Helper SHALL rechazar comandos que contengan caracteres especiales de shell o intentos de inyección
8. THE configuración de sudoers o polkit SHALL permitir al Helper ejecutar únicamente los comandos específicos necesarios (`systemctl poweroff`, `sysctl net.ipv4.icmp_echo_ignore_all`, edición de /etc/hosts)
9. THE Helper SHALL implementar timeout de 5 segundos para cada operación privilegiada y abortar si excede el tiempo
10. IF el Helper detecta un comando malformado o no autorizado, THEN THE Helper SHALL registrar el intento, rechazar el comando y notificar al proceso principal del Client

### Requirement 14: Mecanismos de Seguridad y Recuperación

**User Story:** Como usuario del cliente, quiero tener mecanismos de emergencia para recuperar control de mi máquina, y como administrador, quiero que el sistema sea robusto ante fallos de red o desconexiones.

#### Acceptance Criteria

1. THE Client SHALL implementar un Watchdog que monitorea la conexión con el Server cada 5 segundos
2. WHEN el Watchdog detecta que no ha recibido heartbeat del Server por 10 segundos, THE Watchdog SHALL asumir desconexión
3. WHEN se detecta desconexión, THE Watchdog SHALL ejecutar automáticamente desbloqueo de todos los Input_Device bloqueados
4. THE Client SHALL implementar una hotkey de emergencia (Ctrl+Alt+Shift+U) que desbloquea Input_Device inmediatamente
5. WHEN la hotkey de emergencia es presionada, THE Client SHALL desbloquear Input_Device y registrar el evento como "Desbloqueo de emergencia" en Action_Log
6. THE Server SHALL enviar mensajes heartbeat cada 3 segundos a todos los Client conectados para mantener la conexión activa
7. WHEN un Client no responde a 3 heartbeats consecutivos, THE Server SHALL marcar el Client como desconectado y actualizar el Client_Panel
8. THE Client SHALL mostrar un indicador visual permanente de "Sesión Activa" (por ejemplo: icono en bandeja del sistema) mientras está conectado al Server
9. THE Client SHALL permitir al usuario local ver en cualquier momento el Action_Log de acciones del servidor desde el indicador de sesión
10. WHEN el sistema operativo del Client es reiniciado, THE Client SHALL NO iniciar automáticamente en modo de agente a menos que sea explícitamente configurado por el administrador

### Requirement 15: Interfaz de Usuario y Experiencia

**User Story:** Como administrador del servidor y usuario del cliente, quiero una interfaz intuitiva, clara y en español, para poder operar el sistema eficientemente sin confusión y con feedback inmediato de las acciones.

#### Acceptance Criteria

1. THE Server SHALL mostrar una ventana principal con barra lateral izquierda conteniendo el Client_Panel y área principal con pestañas (Pantalla Remota, Chat, Archivos, Control, Red, Log)
2. THE Server SHALL utilizar tema oscuro por defecto con opción de cambiar a tema claro en la configuración
3. THE Server SHALL utilizar iconos claros y descriptivos para todas las acciones (por ejemplo: 🔒 para bloquear, 🔓 para desbloquear, 🚫 para denegar, ⚡ para apagar)
4. WHEN el administrador ejecuta una acción, THE Server SHALL mostrar feedback inmediato mediante spinner, barra de progreso o notificación toast según el tipo de acción
5. THE Server SHALL utilizar colores semánticos: verde para estados positivos/conectado, rojo para estados negativos/peligro, amarillo para advertencias, azul para información
6. WHEN una acción requiere confirmación, THE Server SHALL mostrar un diálogo modal con descripción clara de la acción y sus consecuencias
7. THE Client SHALL mostrar una ventana mínima o icono de bandeja del sistema con menú contextual para acceder a Chat, Action_Log y estado de conexión
8. THE Client SHALL utilizar ventana semi-transparente (opacidad 85%) para el Action_Log que muestre acciones del servidor sin ocultar completamente el contenido de fondo
9. WHEN el Client está bloqueado, THE Client SHALL mostrar overlay semi-transparente con mensaje "Teclado y Mouse Bloqueados por el Administrador" en el centro de la pantalla
10. ALL las etiquetas, botones, mensajes y textos de la interfaz SHALL estar en español

### Requirement 16: Parser de Protocolo JSON

**User Story:** Como desarrollador del sistema, quiero un parser robusto para el protocolo de comunicación basado en JSON, para asegurar que los mensajes sean correctamente interpretados y que errores de formato sean manejados apropiadamente.

#### Acceptance Criteria

1. WHEN un mensaje es enviado a través del Remote_Control_Protocol, THE emisor SHALL serializar el mensaje como objeto JSON con estructura {"type": "command_name", "payload": {...}, "timestamp": "ISO8601"}
2. WHEN un mensaje JSON es serializado, THE emisor SHALL anteponer 4 bytes conteniendo la longitud del mensaje en formato big-endian para delimitar frames
3. WHEN se recibe un mensaje, THE receptor SHALL leer primero los 4 bytes de longitud, luego leer exactamente esa cantidad de bytes como el frame JSON
4. WHEN el frame es recibido completo, THE receptor SHALL parsear el JSON utilizando parser estándar con manejo de excepciones
5. IF el JSON es malformado o no parseable, THEN THE receptor SHALL registrar error en Action_Log y descartar el mensaje sin cerrar la conexión
6. WHEN un mensaje es parseado exitosamente, THE receptor SHALL validar que contenga los campos obligatorios "type" y "timestamp"
7. THE receptor SHALL validar que el campo "type" corresponda a uno de los comandos en la lista blanca del Remote_Control_Protocol
8. IF la validación falla, THEN THE receptor SHALL registrar el error y rechazar el mensaje
9. THE Parser SHALL soportar mensajes JSON de hasta 10MB de tamaño para acomodar transferencia de frames de pantalla grandes
10. THE Pretty_Printer SHALL formatear mensajes del Remote_Control_Protocol con indentación para logging y debugging durante desarrollo

### Requirement 17: Configuración Externalizada y Segura

**User Story:** Como administrador del sistema, quiero que todas las configuraciones críticas estén en archivos externos con permisos apropiados, para poder modificar parámetros sin recompilar y proteger credenciales sensibles.

#### Acceptance Criteria

1. THE Server SHALL cargar su configuración desde archivo `server_config.json` ubicado en directorio de configuración del usuario (~/.config/remote-monitor/)
2. THE Client SHALL cargar su configuración desde archivo `client_config.json` ubicado en directorio de configuración del usuario (~/.config/remote-monitor/)
3. THE configuración del Server SHALL incluir: puerto de escucha, ruta a certificados TLS, lista de clientes autorizados, timeouts, límites de rate limiting
4. THE configuración del Client SHALL incluir: dirección del Server, puerto, ruta a certificados, Authentication_Token, parámetros de captura de pantalla
5. WHEN el sistema es instalado por primera vez, THE script de instalación SHALL generar archivos de configuración con valores por defecto y permisos 600
6. THE Server y THE Client SHALL validar que los archivos de configuración tengan permisos 600 o más restrictivos al inicio
7. IF los permisos son más permisivos que 600, THEN THE aplicación SHALL mostrar advertencia de seguridad y rechazar iniciar hasta que los permisos sean corregidos
8. THE Authentication_Token SHALL estar almacenado como hash argon2id en el archivo de configuración del Server, nunca en texto plano
9. THE archivos de configuración SHALL NO contener contraseñas en texto plano, rutas de shell arbitrarias, o comandos ejecutables
10. WHEN un parámetro de configuración es inválido o falta, THE aplicación SHALL usar valor por defecto seguro y registrar advertencia en Action_Log

### Requirement 18: Estructura del Proyecto y Modularidad

**User Story:** Como desarrollador del sistema, quiero una estructura de proyecto clara y modular, para facilitar el mantenimiento, pruebas y extensión futura del sistema.

#### Acceptance Criteria

1. THE proyecto SHALL organizarse en directorios: `server/`, `client/`, `helper/`, `common/`, `scripts/`, `tests/`, con archivo `requirements.txt` y `README.md` en la raíz
2. THE directorio `common/` SHALL contener módulos reutilizables: protocol.py (definición del Remote_Control_Protocol), crypto.py (funciones TLS y hashing), utils.py (utilidades comunes)
3. THE directorio `server/` SHALL contener: main.py (punto de entrada), ui.py (interfaz PyQt6), client_manager.py (gestión de conexiones), logger.py (Action_Log)
4. THE directorio `client/` SHALL contener: main.py (punto de entrada), agent.py (lógica de red), ui.py (interfaz mínima), screen_capture.py (captura con mss), executors.py (ejecutores de comandos)
5. THE directorio `helper/` SHALL contener: privileged_helper.py (proceso privilegiado), commands.py (comandos seguros)
6. THE directorio `scripts/` SHALL contener: generate_certs.sh (generación de certificados), install.sh (instalación de dependencias y configuración), setup_systemd.sh (opcional, configuración de servicio)
7. THE directorio `tests/` SHALL contener pruebas unitarias para módulos críticos: protocol parsing, validación de entrada, crypto, y pruebas de integración simuladas
8. THE archivo `requirements.txt` SHALL listar todas las dependencias con versiones pinneadas: PyQt6>=6.6.0, cryptography>=41.0.0, argon2-cffi>=23.0.0, psutil>=5.9.0, mss>=9.0.0, Pillow>=10.0.0
9. THE archivo `README.md` SHALL documentar: descripción del proyecto, requisitos del sistema, instalación paso a paso, configuración, uso básico, arquitectura de seguridad, limitaciones conocidas
10. WHEN se añade una nueva funcionalidad, THE desarrollador SHALL seguir el patrón de separación existente y actualizar la documentación correspondiente

