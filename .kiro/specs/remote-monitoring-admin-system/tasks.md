# Implementation Plan: Remote Monitoring Admin System

## Overview

This implementation plan breaks down the Remote Monitoring Admin System into discrete, implementable tasks. The system is a secure client-server application for monitoring and controlling up to 3 Linux clients simultaneously over TLS-encrypted connections.

**Key Technologies**: Python 3.11+, PyQt6, asyncio, TLS, mss (screen capture), argon2id (authentication)

**Architecture Highlights**:
- Privilege separation: Client agent runs as normal user, separate Helper process for privileged operations
- Custom JSON protocol over TLS with 4-byte framing
- Server manages 3 concurrent client connections with real-time metrics and screen streaming
- Comprehensive audit logging on both server and client sides

## Tasks

- [x] 1. Set up project structure and development environment
  - Create directory structure: `server/`, `client/`, `helper/`, `common/`, `scripts/`, `tests/`
  - Create `requirements.txt` with pinned versions: PyQt6>=6.6.0, cryptography>=41.0.0, argon2-cffi>=23.0.0, psutil>=5.9.0, mss>=9.0.0, Pillow>=10.0.0
  - Create `__init__.py` files for Python packages
  - Set up virtual environment and install dependencies
  - Create basic `.gitignore` for Python projects
  - _Requirements: 18.1, 18.8_

- [ ] 2. Implement common protocol module
  - [-] 2.1 Create protocol message serialization and framing
    - Implement `Protocol.serialize_message(msg_type: str, payload: dict) -> bytes` with 4-byte big-endian length prefix
    - Implement `Protocol.read_message(reader: StreamReader) -> dict | None` to read framed messages
    - Implement JSON serialization with timestamp injection
    - Enforce 10 MB message size limit
    - _Requirements: 16.1, 16.2, 16.3, 16.9_
  
  - [ ]* 2.2 Write property test for protocol serialization
    - **Property 6: Protocol Message Serialization - For any message dictionary containing "type", "payload", and "timestamp" fields, serialization SHALL produce valid JSON that, when parsed, reproduces the original field values**
    - **Property 7: Message Framing Round-Trip - For any protocol message, framing with a 4-byte big-endian length header and then unframing SHALL reproduce the exact original message content**
    - **Validates: Requirements 16.1, 16.2, 16.3**
    - Use Hypothesis library with 100+ iterations
  
  - [~] 2.3 Implement protocol message validation
    - Create command whitelist with all allowed message types (screen_start, screen_stop, input_lock, chat_message, file_init, etc.)
    - Implement `Protocol.validate_message(message: dict) -> bool` checking required fields ("type", "timestamp")
    - Validate command type against whitelist
    - _Requirements: 16.6, 16.7, 12.2_
  
  - [ ]* 2.4 Write property tests for protocol validation
    - **Property 8: Required Field Validation - For any JSON object representing a protocol message, validation SHALL succeed if and only if the object contains "type" and "timestamp" fields**
    - **Property 9: Command Whitelist Enforcement - For any command type string, validation SHALL accept the command if and only if it appears in the predefined whitelist**
    - **Property 15: Message Size Limits - For any protocol message, serialization SHALL enforce a maximum size of 10 MB**
    - **Validates: Requirements 16.6, 16.7, 12.2, 16.9, 12.7**

- [ ] 3. Implement common cryptography module
  - [-] 3.1 Create TLS context setup functions
    - Implement `create_tls_context(cert_path, key_path, ca_path) -> ssl.SSLContext` for server and client
    - Configure TLS 1.3 with strong cipher suites
    - Server context: require and verify client certificates
    - Client context: verify server certificate
    - _Requirements: 11.1, 11.2, 11.10_
  
  - [~] 3.2 Implement authentication utilities
    - Implement `hash_password(password: str) -> str` using argon2id with memory=64MB, iterations=3, parallelism=4
    - Implement `verify_password(password: str, hash_str: str) -> bool`
    - Implement `generate_auth_token() -> str` generating 32-byte random hex token
    - _Requirements: 11.5, 11.6, 11.9_
  
  - [ ]* 3.3 Write unit tests for authentication
    - Test password hashing produces consistent format
    - Test password verification with correct and incorrect passwords
    - Test token generation produces 64-character hex strings
    - Test argon2id parameters are correctly applied

- [ ] 4. Implement common utilities module
  - [-] 4.1 Create validation and sanitization functions
    - Implement `validate_domain(domain: str) -> bool` with regex pattern for valid domains
    - Implement `sanitize_filename(filename: str) -> str` removing path traversal sequences (.., /, null bytes)
    - Implement `validate_path(path: str, allowed_dirs: list) -> bool` preventing path traversal
    - Implement `sanitize_chat_message(message: str) -> str` truncating to 1000 chars and escaping HTML
    - _Requirements: 12.4, 12.5, 12.6, 12.8_
  
  - [ ]* 4.2 Write property tests for validation functions
    - **Property 10: Path Traversal Detection - For any filename string, validation SHALL reject filenames containing "..", "/", or null bytes**
    - **Property 11: Domain Format Validation - For any input string, domain validation SHALL accept valid domain names and reject all others**
    - **Property 12: Chat Message Sanitization - For any input string, SHALL truncate at 1000 characters and escape HTML special characters**
    - **Property 13: Path Containment Validation - For any file path and list of allowed directories, SHALL accept paths only if contained within allowed directories**
    - **Validates: Requirements 12.4, 12.5, 12.6, 12.8**
  
  - [~] 4.3 Create utility helper functions
    - Implement `get_system_info() -> dict` returning OS name, version, hostname
    - Implement `get_cpu_percent() -> float` using psutil
    - Implement `get_memory_percent() -> float` using psutil
    - Implement `format_bytes(size: int) -> str` for human-readable sizes
    - Implement `format_timestamp(dt: datetime) -> str` for consistent timestamp display
    - _Requirements: 4.3, 4.10_

- [ ] 5. Create certificate generation script
  - [-] 5.1 Implement certificate generation script
    - Create `scripts/generate_certs.sh` using OpenSSL commands
    - Generate self-signed CA certificate (4096-bit RSA, 365 days validity)
    - Generate server certificate signed by CA
    - Generate 3 client certificates (client1, client2, client3) signed by CA
    - Create directory structure: `~/.config/remote-monitor/certs/` with subdirectory `authorized_clients/`
    - Set file permissions to 600 for all keys
    - _Requirements: 11.2, 11.3, 17.5_
  
  - [ ]* 5.2 Test certificate generation and validation
    - Verify generated certificates are valid X.509 format
    - Test TLS handshake with generated certificates
    - Verify certificate expiration dates

- [~] 6. Checkpoint - Foundation complete
  - Ensure all tests pass for common modules
  - Verify certificate generation works correctly
  - Ask the user if questions arise

- [ ] 7. Implement server connection manager
  - [~] 7.1 Create ClientSession data model
    - Implement `ClientSession` dataclass with fields: client_id, hostname, ip_address, os_info, reader, writer, state, last_heartbeat, metrics, capabilities
    - Add state enum: CONNECTING, AUTHENTICATED, ACTIVE, DISCONNECTED
    - Include screen_streaming state, screen_config, active_transfers dict, chat_history list
    - _Requirements: 4.2, 4.3, 11.8_
  
  - [~] 7.2 Implement ConnectionManager class
    - Create `ConnectionManager` class in `server/client_manager.py`
    - Implement `async def start_server(host: str, port: int)` to create TCP server with TLS
    - Implement `async def handle_client(reader, writer)` for new connections
    - Enforce maximum 3 concurrent clients
    - Maintain thread-safe client list using asyncio locks
    - _Requirements: 4.2, 11.4, 11.7_
  
  - [~] 7.3 Implement client authentication
    - Implement `async def authenticate_client(reader, writer) -> ClientSession | None`
    - Perform TLS handshake and verify client certificate against authorized_clients directory
    - Receive auth_token message and verify using argon2id hash comparison
    - Create ClientSession on successful authentication
    - Send auth_success or auth_failed response
    - Log authentication attempts (successful and failed)
    - _Requirements: 11.4, 11.5, 11.6, 11.7_
  
  - [~] 7.4 Implement message sending and heartbeat
    - Implement `async def send_message(client_id: str, message: dict)` with protocol framing
    - Implement `async def broadcast_heartbeat()` sending heartbeat every 3 seconds to all connected clients
    - Implement heartbeat timeout detection (mark disconnected after 3 missed heartbeats)
    - Implement `async def disconnect_client(client_id: str)` for graceful disconnection
    - _Requirements: 14.6, 14.7_
  
  - [ ]* 7.5 Write integration tests for connection management
    - Test TLS handshake with valid and invalid certificates
    - Test authentication with correct and incorrect tokens
    - Test maximum 3 client limit enforcement
    - Test heartbeat and disconnect detection

- [ ] 8. Implement server action logger
  - [~] 8.1 Create ActionLogger class
    - Implement `ActionLogger` class in `server/logger.py`
    - Implement `LogEntry` dataclass: timestamp, client_hostname, action_type, description
    - Implement `log_event(client_hostname: str, action: str, description: str)` appending to file and in-memory cache
    - Log format: `[YYYY-MM-DD HH:MM:SS] [Cliente: hostname] [ACTION] Description`
    - Daily log files: `~/.config/remote-monitor/logs/action_log_YYYYMMDD.txt`
    - Maintain in-memory cache of last 500 entries
    - _Requirements: 5.1, 5.2, 5.3_
  
  - [~] 8.2 Implement log retrieval and filtering
    - Implement `get_recent_logs(count: int) -> list[LogEntry]`
    - Implement `filter_logs(client: str | None, action_type: str | None) -> list[LogEntry]`
    - Implement `export_logs(filepath: str)` to export full log to text file
    - _Requirements: 5.4, 5.5_
  
  - [ ]* 8.3 Write unit tests for logger
    - Test log entry formatting
    - Test daily log file rotation
    - Test in-memory cache size limit (500 entries)
    - Test filtering by client and action type

- [ ] 9. Implement server file transfer handler
  - [~] 9.1 Create FileTransfer data model
    - Implement `FileTransfer` dataclass: file_id, filename, direction, total_size, transferred_bytes, chunk_size (64KB), checksum, state, timestamps
    - Implement `TransferState` enum: INIT, TRANSFERRING, VERIFYING, COMPLETE, FAILED
    - _Requirements: 2.4, 2.7_
  
  - [~] 9.2 Implement file sending logic
    - Implement `FileTransferHandler` class in `server/file_handler.py`
    - Implement `async def send_file(client_id: str, filepath: str, progress_callback)`
    - Calculate SHA-256 checksum before transfer
    - Send file_init message with filename, size, checksum
    - Read and send 64KB chunks with file_chunk messages
    - Wait for file_chunk_ack after each chunk
    - Handle file_verified or file_failed response
    - _Requirements: 2.1, 2.3, 2.4, 2.7_
  
  - [~] 9.3 Implement file receiving logic
    - Implement `async def receive_file(client_id: str, save_path: str, progress_callback)`
    - Handle file_init message and send file_accept
    - Receive and write file_chunk messages sequentially
    - Send file_chunk_ack after each chunk
    - Calculate SHA-256 checksum after all chunks received
    - Compare with expected checksum and send file_complete
    - Delete file if checksum mismatch
    - _Requirements: 2.4, 2.6, 2.7, 2.8, 2.9_
  
  - [ ]* 9.4 Write property tests for file transfer
    - **Property 1: Checksum Determinism - For any file content, calculating SHA-256 multiple times SHALL produce identical hash**
    - **Property 2: File Chunking Correctness - For any file size, dividing into 64KB chunks and reassembling SHALL reproduce original content exactly**
    - **Property 3: Transfer Progress Calculation - For any (bytes_transferred, total_bytes), progress percentage SHALL be accurate**
    - **Validates: Requirements 2.3, 2.4, 2.6, 2.7**
  
  - [ ]* 9.5 Write integration tests for file transfer
    - Test end-to-end file transfer with various file sizes
    - Test checksum mismatch handling
    - Test file not found error
    - Test progress callback updates
    - _Requirements: 2.10_

- [ ] 10. Implement server UI foundation
  - [~] 10.1 Create MainWindow and application structure
    - Implement `ServerApplication` class in `server/main.py`
    - Load configuration from `~/.config/remote-monitor/server_config.json`
    - Set up TLS context with server certificates
    - Create asyncio event loop in separate thread
    - Create `MainWindow(QMainWindow)` in `server/ui.py`
    - Set up left sidebar for ClientPanel and main QTabWidget area
    - Implement Spanish UI labels and dark theme
    - _Requirements: 15.1, 15.2, 15.10, 17.1, 17.2, 17.3_
  
  - [~] 10.2 Implement ClientPanel with 3 client slots
    - Create `ClientPanel(QWidget)` with 3 `ClientSlot(QFrame)` widgets arranged vertically
    - Each slot displays: hostname, IP, OS, connection status indicator (green/gray circle)
    - Implement click-to-select behavior with blue border highlight for selected slot
    - Update slot state when client connects/disconnects
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.7, 4.8_
  
  - [~] 10.3 Implement client metrics display and updates
    - Add CPU% and RAM% labels to each ClientSlot
    - Add 160x120px thumbnail QLabel to each slot
    - Implement timer to request metrics every 2 seconds for connected clients
    - Implement timer to request thumbnail every 5 seconds for connected clients
    - Display metrics from metrics_response messages
    - Display thumbnail from thumbnail_response messages
    - _Requirements: 4.5, 4.6, 4.10_
  
  - [ ]* 10.4 Write unit tests for UI components
    - Test ClientSlot state updates (connected, disconnected, selected)
    - Test metrics display formatting
    - Test thumbnail scaling and display

- [ ] 11. Implement server UI tabs
  - [~] 11.1 Create ScreenTab for remote screen viewing
    - Implement `ScreenTab(QWidget)` in `server/ui.py`
    - Add QLabel for displaying screen frames
    - Add resolution dropdown (640x480, 800x600, 1024x768, native)
    - Add quality slider (50-90 JPEG quality)
    - Add Start/Stop streaming button
    - Add FPS counter and bandwidth usage labels
    - Send screen_start command with selected parameters
    - Receive and display screen_frame messages
    - Send screen_stop command when stopped
    - _Requirements: 1.1, 1.4, 1.5, 1.6, 1.7_
  
  - [~] 11.2 Create ChatTab for bidirectional messaging
    - Implement `ChatTab(QWidget)` in `server/ui.py`
    - Add QTextEdit (read-only) for chat history
    - Add QLineEdit and Send button for input
    - Format messages as `[HH:MM:SS] Emisor: mensaje`
    - Send chat_message commands to selected client
    - Receive and display chat_message from client
    - Auto-scroll to latest message
    - Maintain last 200 messages in memory
    - Reject messages over 1000 characters
    - _Requirements: 3.1, 3.3, 3.4, 3.5, 3.6, 3.7, 3.10_
  
  - [ ]* 11.3 Write property tests for chat functionality
    - **Property 4: Chat Message Formatting - For any valid message and timestamp, formatting SHALL produce string matching `[HH:MM:SS] Sender: message`**
    - **Property 5: Message History Bounds - For any sequence of messages, history SHALL contain at most 200 messages**
    - **Validates: Requirements 3.5, 3.6**
  
  - [~] 11.4 Create FilesTab for file transfers
    - Implement `FilesTab(QWidget)` in `server/ui.py`
    - Add "Enviar Archivo" section: file path input, Browse button, Send button
    - Add "Recibir Archivo" section: save path input, Browse button, Request button
    - Add progress bars showing percentage, speed (MB/s), ETA for active transfers
    - Wire to FileTransferHandler methods
    - Show success/failure notifications
    - _Requirements: 2.1, 2.2, 2.6, 2.10_
  
  - [~] 11.5 Create ControlTab for input and power control
    - Implement `ControlTab(QWidget)` in `server/ui.py`
    - Add "Bloquear Teclado/Mouse" button sending input_lock command
    - Add "Desbloquear Teclado/Mouse" button sending input_unlock command
    - Add "Apagar Cliente" button with confirmation dialog showing shutdown warning
    - Display current lock state (Bloqueado/Desbloqueado)
    - Handle command_ack responses updating UI state
    - _Requirements: 6.1, 6.2, 7.1, 7.2, 8.1, 8.2, 8.3_
  
  - [~] 11.6 Create NetworkTab for web and ICMP control
    - Implement `NetworkTab(QWidget)` in `server/ui.py`
    - Add domain blocklist section: QListWidget, input field, "Agregar Dominio" button, "Quitar Dominio" button
    - Validate domain format before sending domain_block command
    - Maintain and display current blocklist
    - Add ICMP control section: "Denegar Ping" and "Permitir Ping" buttons
    - Display current ping state (Permitido/Denegado)
    - _Requirements: 9.1, 9.2, 9.3, 9.7, 9.8, 10.1, 10.2, 10.6, 10.7_
  
  - [~] 11.7 Create LogTab for action log display
    - Implement `LogTab(QWidget)` in `server/ui.py`
    - Add QTableWidget with columns: Timestamp, Cliente, Acción, Descripción
    - Add filter controls: Client dropdown, Action type dropdown
    - Add "Exportar Log" button calling ActionLogger.export_logs()
    - Connect to ActionLogger to display recent logs
    - Update table when new log entries are added
    - _Requirements: 5.1, 5.4, 5.5_

- [~] 12. Checkpoint - Server UI and core complete
  - Test server startup and configuration loading
  - Test UI displays correctly with all tabs
  - Test client connection and disconnection updates UI
  - Ensure all tests pass
  - Ask the user if questions arise

- [ ] 13. Implement client agent core
  - [~] 13.1 Create ClientAgent class and connection logic
    - Implement `ClientAgent` class in `client/agent.py`
    - Load configuration from `~/.config/remote-monitor/client_config.json`
    - Implement `async def connect(server_host: str, port: int)` establishing TLS connection
    - Create TLS context verifying server certificate
    - Implement connection state machine: DISCONNECTED, CONNECTING, AUTHENTICATING, CONNECTED
    - _Requirements: 11.1, 11.8, 17.2, 17.4_
  
  - [~] 13.2 Implement client authentication flow
    - Implement `async def authenticate()` sending auth_token message
    - Load authentication token from config and send to server
    - Wait for auth_success or auth_failed response
    - Store client_id from auth_success
    - Transition to CONNECTED state on success
    - _Requirements: 11.5, 11.8_
  
  - [~] 13.3 Implement message loop and command dispatcher
    - Implement `async def message_loop()` reading and processing messages continuously
    - Implement `async def dispatch_command(message: dict)` routing to appropriate handler
    - Implement `async def send_response(response: dict)` sending protocol messages
    - Handle protocol errors gracefully (malformed JSON, unknown commands)
    - _Requirements: 12.1, 12.2, 12.3_
  
  - [~] 13.4 Implement heartbeat monitoring
    - Implement `async def heartbeat_monitor()` checking last_heartbeat timestamp every 5 seconds
    - Respond to heartbeat messages with heartbeat_ack
    - Update last_heartbeat timestamp on each received heartbeat
    - Trigger watchdog if no heartbeat received for 10 seconds
    - _Requirements: 14.1, 14.2, 14.6_

- [ ] 14. Implement client screen capture module
  - [~] 14.1 Create ScreenCapturer class
    - Implement `ScreenCapturer` class in `client/screen_capture.py`
    - Initialize mss instance for screen capture
    - Implement `get_screen_dimensions() -> tuple` returning native resolution
    - _Requirements: 1.8_
  
  - [~] 14.2 Implement screen capture and streaming loop
    - Implement `async def start_capture(resolution: tuple, quality: int, fps: int)` starting capture loop
    - Implement `async def capture_frame() -> bytes` capturing single frame
    - Use mss to capture full screen as raw RGBA pixels
    - Convert to PIL Image, scale to target resolution using LANCZOS resampling
    - Compress to JPEG with specified quality
    - Encode as base64 for JSON transport
    - Send screen_frame message with encoded data
    - Implement async sleep between frames to achieve target FPS
    - Implement `async def stop_capture()` to stop loop
    - _Requirements: 1.2, 1.3, 1.5, 1.8_
  
  - [ ]* 14.3 Write unit tests for screen capture
    - Test frame compression at different quality levels
    - Test resolution scaling
    - Test base64 encoding/decoding
    - Mock mss to avoid dependency on display
    - _Requirements: 1.9_

- [ ] 15. Implement client privileged helper
  - [~] 15.1 Create PrivilegedHelper process
    - Implement `PrivilegedHelper` class in `helper/privileged_helper.py`
    - Create Unix domain socket at `/tmp/remote-monitor-helper-{pid}.sock`
    - Set socket permissions to 600 (owner read/write only)
    - Implement `async def start()` creating socket and listening for requests
    - Implement `async def handle_request(command: str, params: dict) -> dict` dispatching to command handlers
    - _Requirements: 13.1, 13.2, 13.4_
  
  - [~] 15.2 Implement whitelisted privileged commands
    - Define ALLOWED_COMMANDS whitelist: shutdown, block_domain, unblock_domain, disable_ping, enable_ping, lock_input, unlock_input
    - Implement `shutdown()` executing `systemctl poweroff`
    - Implement `block_domain(domain: str)` appending `127.0.0.1 domain` to `/etc/hosts`
    - Implement `unblock_domain(domain: str)` removing line from `/etc/hosts`
    - Implement `disable_ping()` executing `sysctl -w net.ipv4.icmp_echo_ignore_all=1`
    - Implement `enable_ping()` executing `sysctl -w net.ipv4.icmp_echo_ignore_all=0`
    - Implement `lock_input()` executing `xinput disable` for each keyboard/mouse device
    - Implement `unlock_input()` executing `xinput enable` for each keyboard/mouse device
    - Use subprocess with explicit arguments (never shell=True)
    - _Requirements: 6.3, 7.3, 8.6, 9.4, 9.5, 9.9, 10.3, 10.8, 13.4_
  
  - [~] 15.3 Implement helper security validation
    - Validate all command parameters with strict regex patterns
    - Reject commands with shell metacharacters: `;`, `|`, `&`, `$`, `` ` ``, `\n`
    - Implement 5-second timeout for each operation
    - Log all commands to `/var/log/remote-monitor-helper.log` (requires root)
    - Return success/failure with descriptive messages
    - _Requirements: 13.5, 13.6, 13.7, 13.9_
  
  - [ ]* 15.4 Write unit tests for helper validation
    - Test command whitelist enforcement
    - Test shell metacharacter rejection
    - Test parameter validation (domain format, etc.)
    - Test timeout enforcement
    - Mock actual system commands (xinput, systemctl, etc.)
    - _Requirements: 13.10_
  
  - [~] 15.5 Create helper installation script
    - Create `scripts/setup_helper.sh` configuring sudoers or systemd service
    - Add sudoers entry: `remote-monitor-user ALL=(ALL) NOPASSWD: /opt/remote-monitor/helper/privileged_helper.py`
    - Alternative: create systemd socket-activated service running as root
    - _Requirements: 8.7, 13.8, 13.10_

- [ ] 16. Implement client command executors
  - [~] 16.1 Implement screen streaming command handlers
    - Implement `async def handle_screen_start(params)` in `client/executors.py`
    - Extract resolution, quality, fps from params
    - Start ScreenCapturer with specified config
    - Implement `async def handle_screen_stop()` stopping capture
    - _Requirements: 1.1, 1.4, 1.5_
  
  - [~] 16.2 Implement input control command handlers
    - Implement `async def handle_input_lock()` calling helper lock_input
    - Show "Teclado y Mouse Bloqueados por el Administrador" overlay in UI
    - Send command_ack with success/failure
    - Implement `async def handle_input_unlock()` calling helper unlock_input
    - Hide lock overlay in UI
    - Send command_ack
    - _Requirements: 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_
  
  - [~] 16.3 Implement shutdown command handler
    - Implement `async def handle_shutdown(countdown: int)` showing countdown dialog
    - Display full-screen modal with countdown timer updating every second
    - After countdown reaches 0, call helper shutdown
    - _Requirements: 8.3, 8.4, 8.5, 8.6_
  
  - [~] 16.4 Implement network control command handlers
    - Implement `async def handle_domain_block(domain: str)` calling helper block_domain
    - Implement `async def handle_domain_unblock(domain: str)` calling helper unblock_domain
    - Implement `async def handle_ping_control(allow: bool)` calling helper disable_ping or enable_ping
    - Send command_ack responses
    - _Requirements: 9.4, 9.5, 9.6, 9.9, 10.3, 10.8, 10.9_
  
  - [~] 16.5 Implement chat and file transfer handlers
    - Implement `async def handle_chat_message(message: str)` displaying in chat window
    - Implement file transfer protocol handlers: handle_file_init, handle_file_chunk, etc.
    - Mirror server-side file transfer logic for bidirectional transfers
    - _Requirements: 2.2, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 3.4_
  
  - [~] 16.6 Implement metrics and thumbnail request handlers
    - Implement `async def handle_metrics_request()` using psutil to get CPU/RAM
    - Send metrics_response message
    - Implement `async def handle_thumbnail_request()` capturing 160x120px thumbnail
    - Send thumbnail_response message
    - _Requirements: 4.5, 4.6, 4.10_

- [ ] 17. Implement client watchdog
  - [~] 17.1 Create Watchdog class
    - Implement `Watchdog` class in `client/watchdog.py`
    - Implement `async def start()` beginning heartbeat monitoring
    - Implement `def heartbeat_received()` resetting heartbeat timer
    - _Requirements: 14.1, 14.5_
  
  - [~] 17.2 Implement auto-unlock on disconnect
    - Implement `async def check_connection()` checking heartbeat timestamp every 5 seconds
    - If no heartbeat for 10 seconds, call `trigger_emergency_unlock()`
    - Implement `async def trigger_emergency_unlock()` calling helper unlock_input
    - Log emergency unlock event to client action log
    - _Requirements: 7.9, 14.2, 14.3_
  
  - [ ]* 17.3 Write integration tests for watchdog
    - Test auto-unlock triggered after 10 seconds without heartbeat
    - Test heartbeat_received resets timer correctly
    - Mock helper calls

- [ ] 18. Implement client UI
  - [~] 18.1 Create client system tray application
    - Implement `ClientTrayApp(QSystemTrayIcon)` in `client/ui.py`
    - Icon changes based on connection state: green=connected, gray=disconnected, yellow=connecting, red=error
    - Context menu: "Ver Chat", "Ver Log de Acciones", "Estado", "Salir"
    - _Requirements: 15.7, 15.8, 14.8_
  
  - [~] 18.2 Create ChatWindow for client
    - Implement `ChatWindow(QWidget)` showing chat history (read-only QTextEdit)
    - Add input field and Send button
    - Format messages as `[HH:MM:SS] Emisor: mensaje` (Cliente: for local, Servidor: for remote)
    - Send chat_message to server when user sends
    - _Requirements: 3.2, 3.4, 3.9_
  
  - [~] 18.3 Create ActionLogWindow
    - Implement `ActionLogWindow(QWidget)` with semi-transparent background (85% opacity)
    - Always on top, non-modal
    - Table showing last 100 server actions with timestamp, action, description
    - Auto-update when new actions logged
    - _Requirements: 5.6, 5.7, 5.8, 5.10, 14.9_
  
  - [~] 18.4 Create InputBlockOverlay
    - Implement `InputBlockOverlay(QWidget)` full-screen semi-transparent (60% opacity)
    - Centered text: "🔒 Teclado y Mouse Bloqueados por el Administrador"
    - No window controls, no cancel button
    - Show when input_lock command received, hide on input_unlock
    - _Requirements: 6.4, 6.8, 15.9_
  
  - [~] 18.5 Create ShutdownCountdownDialog
    - Implement `ShutdownCountdownDialog(QDialog)` full-screen modal
    - Large countdown number updating every second
    - Text: "⚡ El sistema se apagará en [X] segundos"
    - No cancel button
    - _Requirements: 8.4, 8.5, 15.9_
  
  - [~] 18.6 Implement emergency unlock hotkey
    - Register global hotkey listener for Ctrl+Alt+Shift+U
    - When pressed, call `agent.emergency_unlock()` calling helper unlock_input immediately
    - Log as "Desbloqueo de emergencia" in action log
    - _Requirements: 7.10, 14.4, 14.5_

- [ ] 19. Implement client action logging
  - [~] 19.1 Create client-side ActionLogger
    - Implement `ActionLogger` in `client/agent.py` or separate module
    - Log format: `[HH:MM:SS] Servidor ejecutó: [Acción]`
    - Log events: conexión, desconexión, comandos recibidos, screen capture start/stop, input lock/unlock, domain block/unblock, ICMP changes
    - Daily log files: `~/.config/remote-monitor/logs/action_log_YYYYMMDD.txt`
    - _Requirements: 5.6, 5.7, 5.9_
  
  - [~] 19.2 Wire action logging to command handlers
    - Log each command received from server before executing
    - Log completion or failure after execution
    - Display in ActionLogWindow in real-time
    - Maintain only last 100 entries in window display
    - _Requirements: 5.8, 5.10, 8.8, 9.6, 10.4_

- [~] 20. Checkpoint - Client implementation complete
  - Test client connection to server
  - Test all command handlers (screen streaming, input lock, shutdown, etc.)
  - Test watchdog auto-unlock functionality
  - Test emergency hotkey
  - Verify UI components display correctly
  - Ensure all tests pass
  - Ask the user if questions arise

- [ ] 21. Implement rate limiting
  - [~] 21.1 Create rate limiter decorator
    - Implement `rate_limiter(max_calls: int, period: float)` decorator in `common/utils.py`
    - Token bucket algorithm implementation
    - _Requirements: 12.10_
  
  - [~] 21.2 Apply rate limiting to message handling
    - Apply rate limiter to ConnectionManager.handle_client (100 messages/second per client)
    - Reject messages exceeding rate limit
    - Log rate limit violations
    - Close connection after sustained violations (3 consecutive violations)
    - _Requirements: 12.10_
  
  - [ ]* 21.3 Write property test for rate limiting
    - **Property 14: Rate Limiting Enforcement - For any sequence of messages within 1-second window, SHALL accept at most 100 messages**
    - **Validates: Requirements 12.10**

- [ ] 22. Implement configuration management
  - [~] 22.1 Create configuration file templates
    - Create `server_config.json` template with default values
    - Create `client_config.json` template with default values
    - Document all configuration parameters
    - _Requirements: 17.1, 17.2, 17.3, 17.4_
  
  - [~] 22.2 Implement configuration loading and validation
    - Implement config loading in ServerApplication and ClientAgent
    - Validate file permissions are 600 or more restrictive
    - Refuse to start if permissions too permissive
    - Show warning dialog if configuration invalid
    - Use secure defaults for missing values
    - _Requirements: 17.5, 17.6, 17.7, 17.9, 17.10_
  
  - [ ]* 22.3 Write unit tests for configuration
    - Test config loading with valid and invalid JSON
    - Test permission validation
    - Test default value fallback
    - Test expansion of paths with ~

- [ ] 23. Implement installation and deployment scripts
  - [~] 23.1 Create installation script
    - Create `scripts/install.sh` automating installation process
    - Check for Python 3.11+ and required system dependencies
    - Create directory structure in ~/.config/remote-monitor/
    - Install Python dependencies from requirements.txt
    - Generate default configuration files with secure permissions
    - Run certificate generation script
    - Generate initial authentication token
    - _Requirements: 17.5, 18.6, 18.8_
  
  - [~] 23.2 Create systemd service files
    - Create server service file: `/etc/systemd/system/remote-monitor-server.service`
    - Create client service file: `/etc/systemd/system/remote-monitor-client.service`
    - Create helper service file: `/etc/systemd/system/remote-monitor-helper.service`
    - Document service installation and enablement
    - _Requirements: 18.7_
  
  - [ ]* 23.3 Test installation process
    - Test fresh installation on clean Ubuntu 22.04 VM
    - Verify all dependencies installed correctly
    - Verify services start successfully
    - Test uninstall process

- [ ] 24. Create comprehensive documentation
  - [~] 24.1 Write README.md
    - Project description and features overview
    - System requirements (Linux, X11, Python 3.11+)
    - Installation instructions (step-by-step)
    - Basic usage guide (starting server, connecting clients)
    - Architecture overview (privilege separation, TLS security)
    - Known limitations (Wayland not fully supported)
    - _Requirements: 18.9, 18.10_
  
  - [~] 24.2 Write troubleshooting guide
    - Common issues and solutions
    - Debugging tips (log locations, verbose mode)
    - Performance tuning recommendations
    - Network configuration requirements
    - _Requirements: 18.10_
  
  - [ ]* 24.3 Create demo/tutorial script
    - Step-by-step tutorial demonstrating all features
    - Screenshots or ASCII art diagrams
    - Sample configuration files

- [ ] 25. Security hardening review
  - [~] 25.1 Review and test input validation
    - Verify all user inputs validated and sanitized
    - Test SQL injection, command injection, path traversal attempts
    - Test XSS in chat messages
    - Test oversized messages rejected
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 12.8, 12.9_
  
  - [~] 25.2 Review privilege separation
    - Verify client agent runs with normal user privileges
    - Verify helper only accepts whitelisted commands
    - Test privilege escalation attempts
    - Review sudoers configuration security
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.7, 13.8, 13.9, 13.10_
  
  - [~] 25.3 Review TLS and authentication
    - Verify certificate validation enforced
    - Test connection with invalid certificates
    - Test authentication with wrong tokens
    - Verify no plaintext credentials in config files
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.9, 17.8_

- [ ] 26. Integration and end-to-end testing
  - [ ]* 26.1 Write end-to-end test suite
    - Test complete workflow: install, start server, connect 3 clients
    - Test screen streaming from all clients simultaneously
    - Test file transfer bidirectionally
    - Test chat with all clients
    - Test input lock/unlock on each client
    - Test domain blocking on each client
    - Test ICMP control on each client
    - Test shutdown on one client
    - Test watchdog auto-unlock when server disconnected
    - Test action logs on server and clients
  
  - [ ]* 26.2 Performance testing
    - Test CPU usage with 3 clients streaming screens
    - Test memory usage over extended period (memory leaks)
    - Test network bandwidth with concurrent operations
    - Test file transfer speeds (target: >10 MB/s on LAN)
    - Verify target: 8 FPS at 1024x768 with <10% CPU per client
  
  - [ ]* 26.3 Stress testing
    - Test rapid connect/disconnect cycles
    - Test message flooding (verify rate limiting works)
    - Test with poor network conditions (packet loss, latency)
    - Test recovery after network outages

- [~] 27. Final checkpoint and user acceptance
  - Verify all functional requirements implemented and working
  - Verify all security requirements implemented
  - Run complete test suite and ensure all tests pass
  - Review code for TODOs and unfinished sections
  - Perform final code cleanup and documentation review
  - Create release package with binaries, scripts, and documentation
  - Ask the user for final review and acceptance

## Notes

- **Optional Tasks**: Tasks marked with `*` are optional test tasks that can be skipped for faster MVP delivery, though they're recommended for production quality
- **Testing Strategy**: Property-based tests validate universal correctness properties; integration tests verify system interactions; unit tests cover specific scenarios
- **Property-Based Tests**: All property tests MUST use Hypothesis library with minimum 100 iterations
- **Security Focus**: Input validation, privilege separation, and TLS security are critical and must be thoroughly tested
- **Linux/X11 Dependency**: System is designed for Linux with X11; Wayland support is limited (input blocking not supported)
- **Checkpoints**: Strategically placed to ensure incremental validation and allow user feedback
- **Dependencies**: Each task builds on previous tasks in logical order (common modules → server → client → helper → integration)
- **Testing Coverage**: Mix of property-based tests (for algorithmic correctness), unit tests (for specific behavior), and integration tests (for system interactions)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1", "3.1", "4.1", "5.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.2", "3.3", "4.2", "4.3", "5.2"] },
    { "id": 3, "tasks": ["2.4"] },
    { "id": 4, "tasks": ["7.1", "8.1", "9.1"] },
    { "id": 5, "tasks": ["7.2", "7.3", "8.2", "9.2"] },
    { "id": 6, "tasks": ["7.4", "7.5", "8.3", "9.3", "9.4", "9.5"] },
    { "id": 7, "tasks": ["10.1", "10.2"] },
    { "id": 8, "tasks": ["10.3", "10.4"] },
    { "id": 9, "tasks": ["11.1", "11.2", "11.3", "11.4", "11.5", "11.6", "11.7"] },
    { "id": 10, "tasks": ["13.1", "14.1", "15.1"] },
    { "id": 11, "tasks": ["13.2", "13.3", "14.2", "15.2"] },
    { "id": 12, "tasks": ["13.4", "14.3", "15.3", "15.4", "15.5"] },
    { "id": 13, "tasks": ["16.1", "16.2", "16.3", "16.4", "16.5", "16.6", "17.1"] },
    { "id": 14, "tasks": ["17.2", "17.3", "18.1"] },
    { "id": 15, "tasks": ["18.2", "18.3", "18.4", "18.5", "18.6", "19.1"] },
    { "id": 16, "tasks": ["19.2"] },
    { "id": 17, "tasks": ["21.1", "22.1"] },
    { "id": 18, "tasks": ["21.2", "21.3", "22.2", "22.3"] },
    { "id": 19, "tasks": ["23.1", "23.2"] },
    { "id": 20, "tasks": ["23.3", "24.1", "24.2", "24.3"] },
    { "id": 21, "tasks": ["25.1", "25.2", "25.3"] },
    { "id": 22, "tasks": ["26.1", "26.2", "26.3"] }
  ]
}
```
