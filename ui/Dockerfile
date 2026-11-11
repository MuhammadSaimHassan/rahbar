FROM nginx:1.30.6-alpine

RUN apk upgrade --no-cache libxslt

COPY nginx.conf /etc/nginx/nginx.conf
COPY index.html /usr/share/nginx/html/index.html

USER 101:101
EXPOSE 8080
# Start nginx directly: the base entrypoint edits config files on a read-only root.
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
