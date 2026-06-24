FROM alpine:3.20

ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown
ARG IMAGE_TAG=unknown

RUN apk add --no-cache \
      ca-certificates \
      curl \
      jq && \
    update-ca-certificates && \
    ARCH="$(uname -m)" && \
    case "$ARCH" in \
      x86_64) K_ARCH=amd64 ;; \
      aarch64|arm64) K_ARCH=arm64 ;; \
      *) K_ARCH=arm64 ;; \
    esac && \
    KUBECTL_VERSION="v1.30.0" && \
    curl -fsSLo /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${K_ARCH}/kubectl" && \
    chmod +x /usr/local/bin/kubectl

ENV VERIFIER_GIT_SHA=$GIT_SHA \
    VERIFIER_BUILD_TIME=$BUILD_TIME \
    VERIFIER_IMAGE_TAG=$IMAGE_TAG

WORKDIR /scripts

# The deploy-verify.sh script is provided via ConfigMap at runtime and mounted
# into /scripts. This image only needs to provide tooling (curl, jq, kubectl).

ENTRYPOINT ["/bin/sh","-c"]
CMD ["/scripts/deploy-verify.sh"]
