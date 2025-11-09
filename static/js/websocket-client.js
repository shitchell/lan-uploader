/**
 * WebSocket client for real-time upload progress tracking
 *
 * Manages WebSocket connection to backend, handles session ID exchange,
 * and provides event-driven message handling for upload progress, errors,
 * and completion notifications.
 */
class UploadWebSocketClient {
    /**
     * Create a new WebSocket client
     * @param {string} baseUrl - Base URL for WebSocket connection (optional, defaults to current host)
     */
    constructor(baseUrl) {
        // Determine base URL with correct protocol (ws:// or wss://)
        this.baseUrl = baseUrl || `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}`;

        this.socket = null;
        this.sessionId = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 1000; // 1 second base delay
        this.messageHandlers = {}; // { messageType: [handler1, handler2, ...] }
        this.connectionPromise = null;
        this.pingInterval = null;
    }

    /**
     * Connect to WebSocket server and wait for session_id
     * @returns {Promise<string>} Session ID assigned by server
     */
    async connect() {
        // Prevent multiple simultaneous connection attempts
        if (this.connectionPromise) {
            return this.connectionPromise;
        }

        this.connectionPromise = new Promise((resolve, reject) => {
            const wsUrl = `${this.baseUrl}/api/upload/ws`;
            console.log('Connecting to WebSocket:', wsUrl);

            try {
                this.socket = new WebSocket(wsUrl);
            } catch (error) {
                console.error('Failed to create WebSocket:', error);
                reject(error);
                return;
            }

            // Connection opened
            this.socket.onopen = () => {
                console.log('WebSocket connected');
                this.reconnectAttempts = 0;
                this.startPingInterval();
            };

            // Message received
            this.socket.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    console.log('WebSocket message:', data);

                    // Handle session_id message (connection confirmation)
                    if (data.type === 'session_id') {
                        this.sessionId = data.id;
                        console.log('Received session ID:', this.sessionId);
                        resolve(data.id);
                    }

                    // Call registered handlers for this message type
                    if (this.messageHandlers[data.type]) {
                        this.messageHandlers[data.type].forEach(handler => {
                            try {
                                handler(data);
                            } catch (e) {
                                console.error('Error in message handler:', e);
                            }
                        });
                    }
                } catch (e) {
                    console.error('Error parsing WebSocket message:', e);
                }
            };

            // Connection error
            this.socket.onerror = (error) => {
                console.error('WebSocket error:', error);
                // Only reject if we haven't gotten session_id yet
                if (!this.sessionId) {
                    reject(new Error('WebSocket connection failed'));
                }
            };

            // Connection closed
            this.socket.onclose = (event) => {
                console.log('WebSocket closed:', event.code, event.reason);
                this.stopPingInterval();

                // Attempt reconnection if we were previously connected
                // and haven't exceeded max attempts
                if (this.sessionId && this.reconnectAttempts < this.maxReconnectAttempts) {
                    console.log('Connection lost, attempting to reconnect...');
                    this.reconnect();
                }
            };

            // Timeout if we don't get session_id within 10 seconds
            setTimeout(() => {
                if (!this.sessionId) {
                    reject(new Error('WebSocket connection timeout'));
                    if (this.socket) {
                        this.socket.close();
                    }
                }
            }, 10000);
        });

        return this.connectionPromise;
    }

    /**
     * Attempt to reconnect after disconnect
     * Uses exponential backoff for retry delay
     */
    async reconnect() {
        this.reconnectAttempts++;
        const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);

        console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);

        await new Promise(resolve => setTimeout(resolve, delay));

        // Reset connection state
        this.connectionPromise = null;
        this.sessionId = null;

        try {
            await this.connect();
        } catch (error) {
            console.error('Reconnection failed:', error);

            // If we've exhausted reconnection attempts, notify handlers
            if (this.reconnectAttempts >= this.maxReconnectAttempts) {
                this._notifyHandlers('error', {
                    type: 'error',
                    message: 'Lost connection to server',
                    code: 'CONNECTION_LOST'
                });
            }
        }
    }

    /**
     * Start sending ping messages to keep connection alive
     */
    startPingInterval() {
        // Send ping every 30 seconds
        this.pingInterval = setInterval(() => {
            if (this.socket && this.socket.readyState === WebSocket.OPEN) {
                try {
                    this.socket.send(JSON.stringify({ type: 'ping' }));
                } catch (e) {
                    console.error('Error sending ping:', e);
                }
            }
        }, 30000);
    }

    /**
     * Stop sending ping messages
     */
    stopPingInterval() {
        if (this.pingInterval) {
            clearInterval(this.pingInterval);
            this.pingInterval = null;
        }
    }

    /**
     * Register a message handler for a specific message type
     * @param {string} messageType - Type of message to handle (e.g., 'progress', 'error')
     * @param {Function} handler - Handler function called with message data
     */
    on(messageType, handler) {
        if (!this.messageHandlers[messageType]) {
            this.messageHandlers[messageType] = [];
        }
        this.messageHandlers[messageType].push(handler);
    }

    /**
     * Unregister a message handler
     * @param {string} messageType - Type of message
     * @param {Function} handler - Handler function to remove
     */
    off(messageType, handler) {
        if (this.messageHandlers[messageType]) {
            this.messageHandlers[messageType] = this.messageHandlers[messageType].filter(h => h !== handler);
        }
    }

    /**
     * Notify handlers of a message (internal use)
     * @param {string} messageType - Type of message
     * @param {Object} data - Message data
     */
    _notifyHandlers(messageType, data) {
        if (this.messageHandlers[messageType]) {
            this.messageHandlers[messageType].forEach(handler => {
                try {
                    handler(data);
                } catch (e) {
                    console.error('Error in message handler:', e);
                }
            });
        }
    }

    /**
     * Close WebSocket connection and clean up resources
     */
    close() {
        console.log('Closing WebSocket connection');
        this.stopPingInterval();

        if (this.socket) {
            // Remove event handlers to prevent reconnection attempts
            this.socket.onclose = null;
            this.socket.onerror = null;
            this.socket.close();
            this.socket = null;
        }

        this.sessionId = null;
        this.connectionPromise = null;
        this.reconnectAttempts = 0;
        this.messageHandlers = {};
    }

    /**
     * Check if WebSocket is supported by the browser
     * @returns {boolean} true if WebSocket is supported
     */
    static isSupported() {
        return 'WebSocket' in window;
    }
}
