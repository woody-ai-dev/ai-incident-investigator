# syntax=docker/dockerfile:1

FROM eclipse-temurin:25.0.4.1_1-jdk-noble AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY .mvn/ ./.mvn/
COPY mvnw pom.xml ./
COPY src/ ./src/

RUN --mount=type=cache,target=/root/.m2 \
    chmod +x mvnw \
    && ./mvnw -B -ntp -DskipTests package

FROM eclipse-temurin:25.0.4.1_1-jre-noble AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app \
        --home-dir /app --no-create-home --shell /usr/sbin/nologin app \
    && install -d -m 0755 -o app -g app /app /data

WORKDIR /app

COPY --from=builder --chown=app:app \
    /build/target/order-service-0.1.0.jar /app/order-service.jar

USER app

EXPOSE 8081

HEALTHCHECK --interval=5s --timeout=5s --start-period=30s --retries=12 \
    CMD ["curl", "--fail", "--silent", "--show-error", "--max-time", "3", "http://127.0.0.1:8081/actuator/health"]

ENTRYPOINT ["java", "-jar", "/app/order-service.jar"]