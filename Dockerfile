# SONDA aislada para validar como Railway ejecuta preDeployCommand con un
# ENTRYPOINT de Dockerfile. Misma base, mismo usuario y mismo ENTRYPOINT que
# CAJAS GABO; sin n8n, sin Postgres de CAJAS GABO, sin Drive, sin secretos.
FROM node:22-bookworm-slim
WORKDIR /app
COPY scripts/ /app/scripts/
RUN chmod +x /app/scripts/*.sh && chown -R node:node /app
ENV PORT=8090
USER node
EXPOSE 8090
ENTRYPOINT ["/app/scripts/railway_entrypoint.sh"]
