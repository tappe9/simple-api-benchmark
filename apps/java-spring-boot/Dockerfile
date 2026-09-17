FROM eclipse-temurin:25-jdk-noble@sha256:9db2c4ebea19768ded62a4ce99d59ec5c1cc1e9753cec27c61f9d9c4c9f6f620 AS build

# The fixed base predates this JDK hotfix. Replace it with the exact verified
# distribution instead of relying on a mutable tag or overlaying old JDK files.
ARG TARGETARCH
RUN set -eu; \
    case "$TARGETARCH" in \
      amd64) arch=x64; jdk_sha=dbb698396d478e7fa2b1e50f4103324b2a99b90569ee27c33f2261f9215cf41e; jre_sha=ebb67d70e5e7cfbe21f3771a40cfe1b2b448c3509ea0a60b75dd54cbdc79b9f69 ;; \
      arm64) arch=aarch64; jdk_sha=69df11a02cfa3ef7d7ca645e03edce6778ec090e100f6ae2b42097865730ac52; jre_sha=4124caf2b6c9c6d5babdfa2f3df795852b80748317890e471d051d0a4793a677b ;; \
      *) echo 'unsupported Java container architecture' >&2; exit 1 ;; \
    esac; \
    base='https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.4.1%2B1'; \
    curl --fail --silent --show-error --location --max-time 180 "$base/OpenJDK25U-jdk_${arch}_linux_hotspot_25.0.4.1_1.tar.gz" -o /tmp/jdk.tar.gz; \
    echo "$jdk_sha  /tmp/jdk.tar.gz" | sha256sum -c -; \
    curl --fail --silent --show-error --location --max-time 180 "$base/OpenJDK25U-jre_${arch}_linux_hotspot_25.0.4.1_1.tar.gz" -o /tmp/jre.tar.gz; \
    echo "$jre_sha  /tmp/jre.tar.gz" | sha256sum -c -; \
    rm -rf /opt/java/openjdk; \
    mkdir -p /opt/java/openjdk /opt/verified-jre; \
    tar -xzf /tmp/jdk.tar.gz --strip-components=1 -C /opt/java/openjdk; \
    tar -xzf /tmp/jre.tar.gz --strip-components=1 -C /opt/verified-jre; \
    rm /tmp/jdk.tar.gz /tmp/jre.tar.gz

WORKDIR /src
COPY .java-version build.gradle settings.gradle gradle.properties gradle.lockfile gradlew ./
COPY gradle/ gradle/
COPY src/main/ src/main/
RUN echo '7a9ce74cff467ca1bf60a4fcd9f05185acceda4d0f382434d393e17864262c5d  gradle/wrapper/gradle-wrapper.jar' | sha256sum -c - \
    && ./gradlew --no-daemon installDist

FROM eclipse-temurin:25-jre-noble@sha256:ae0436887d47df7799d83f822e338a38d31c9a293eb1773cc93c54a10bf09017b
RUN rm -rf /opt/java/openjdk \
    && groupadd --gid 10001 benchmark \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin benchmark
COPY --from=build /opt/verified-jre/ /opt/java/openjdk/
WORKDIR /app
COPY --from=build --chown=10001:10001 /src/build/install/java-spring-boot/lib/ /app/lib/
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=60.0", "-cp", "/app/lib/*", "dev.simpleapibenchmark.BenchmarkApplication"]
CMD []
