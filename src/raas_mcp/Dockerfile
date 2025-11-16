FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY src/mcp/requirements.txt /app/src/mcp/
RUN pip install --no-cache-dir -r /app/src/mcp/requirements.txt

# Copy MCP server code
COPY src/mcp/ /app/src/mcp/

# Set Python path
ENV PYTHONPATH=/app

# Expose port (for potential HTTP wrapper in future)
EXPOSE 5000

# Run the MCP server
CMD ["python", "-m", "src.mcp.server"]
