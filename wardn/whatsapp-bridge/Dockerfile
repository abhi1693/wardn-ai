FROM alpine:3.24@sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b AS source

ARG WA_MEOW_REPOSITORY=https://github.com/abhi1693/wa_meow
ARG WA_MEOW_REF=c641f6528cdc205684a52f708ea5b8c6caaffad5
RUN apk add --no-cache ca-certificates git
WORKDIR /src
RUN git clone "$WA_MEOW_REPOSITORY" . \
    && git checkout "$WA_MEOW_REF"

FROM golang:1.26-alpine3.24@sha256:ce864e7223ac17b1775e6fd0b4c0db580c2eb50e7953a427916379e4b92a1628 AS builder

RUN apk add --no-cache gcc musl-dev sqlite-dev

WORKDIR /app

COPY --from=source /src/go.mod /src/go.sum ./
RUN go get golang.org/x/crypto@v0.55.0 golang.org/x/net@v0.57.0 golang.org/x/text@v0.41.0 \
    && go mod download

COPY --from=source /src/cmd/server ./cmd/server
RUN CGO_ENABLED=1 GOOS=linux go build -o whatsapp-server ./cmd/server

FROM alpine:3.24@sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b

RUN apk upgrade --no-cache \
    && apk add --no-cache ca-certificates sqlite-libs \
    && addgroup -g 1000 wardn \
    && adduser -D -G wardn -u 1000 wardn \
    && mkdir -p /data/whatsapp /licenses/wa_meow \
    && chown -R wardn:wardn /data/whatsapp

WORKDIR /app

COPY --from=builder /app/whatsapp-server ./whatsapp-server
COPY --from=source /src/LICENSE /licenses/wa_meow/LICENSE

ENV DATA_DIR=/data/whatsapp
ENV PORT=8090

USER wardn

EXPOSE 8090

CMD ["./whatsapp-server"]
