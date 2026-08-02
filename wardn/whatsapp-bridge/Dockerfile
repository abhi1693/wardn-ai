FROM alpine:3.22 AS source

ARG WA_MEOW_REF=ae757266b55d29f887d1bb39a50c8125ba4de24b
RUN apk add --no-cache ca-certificates git
WORKDIR /src
RUN git clone https://github.com/jo-inc/wa_meow . \
    && git checkout "$WA_MEOW_REF"

FROM golang:1.25-alpine AS builder

RUN apk add --no-cache gcc musl-dev sqlite-dev

WORKDIR /app

COPY --from=source /src/go.mod /src/go.sum ./
RUN go mod download

COPY --from=source /src/cmd/server ./cmd/server
RUN CGO_ENABLED=1 GOOS=linux go build -o whatsapp-server ./cmd/server

FROM alpine:3.22

RUN apk add --no-cache ca-certificates sqlite-libs \
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
