FROM eclipse-temurin:25-jdk-noble@sha256:9db599e7cdf3f650ba93441ba84020808e9da4834cf079b877f8abea5888d9b7 AS build

# The fixed base predates this JDK hotfix. Replace it with the exact verified
# distribution instead of relying on a mutable tag or overlaying old JDK files.
ARG TARGETARCH
RUN set -eu; \
    case "$TARGETARCH" in \
      amd64) arch=x64; jdk_sha=dbb698396d478e7fa2b1e50f4103324b2a99b90569ee27c33f2261f9215cf41e; jre_sha=1731a34baadec5479258ea0202e4d5d865d2efeee60cb0c7d7eb056fe96ca219 ;; \
      arm64) arch=aarch64; jdk_sha=69df11a02cfa3ef7d7ca645e03edce6778ec090e100f6ae2b42097865730ac52; jre_sha=34828cbb93ed31c281c84ecb31ddab655d11a802f263c1fc019d42e9e0230fed ;; \
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

FROM eclipse-temurin:25-jre-noble@sha256:d0d42862bc6cdcb9bc01096d48753b741316f44af2022666833d94f562b58481
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
