module.exports = {
  apps: [
    {
      name: "mcp-booking-server",
      script: "server.py",
      interpreter: "python",
      args: "--transport sse --host 127.0.0.1 --port 3100",
      cwd: "C:\\Users\\azureuser\\Downloads\\test\\mcp",
      watch: false,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 2000,
      env: {
        MCP_TRANSPORT: "sse",
        MCP_HOST: "127.0.0.1",
        MCP_PORT: "3100",
        MCP_API_KEY: "mcp-secret-key-2026-airline-booking",
        ALLOW_MUTATIONS: "false"
      }
    }
  ]
};
