group "default" {
  targets = ["backend", "model-server", "web"]
}

variable "BACKEND_REPOSITORY" {
  default = "onyx-local/onyx-backend"
}

variable "WEB_SERVER_REPOSITORY" {
  default = "onyx-local/onyx-web-server"
}

variable "MODEL_SERVER_REPOSITORY" {
  default = "onyx-local/onyx-model-server"
}

variable "INTEGRATION_REPOSITORY" {
  default = "onyx-local/onyx-integration"
}

variable "TAG" {
  default = "local-dev"
}

variable "NEXT_PUBLIC_OIDC_LOGIN_PROVIDER" {
  default = ""
}

variable "ENABLE_CRAFT" {
  default = "false"
}

variable "INSTALL_PLAYWRIGHT" {
  default = "false"
}

target "backend" {
  context    = "backend"
  dockerfile = "Dockerfile"

  args = {
    ENABLE_CRAFT     = "${ENABLE_CRAFT}"
    INSTALL_PLAYWRIGHT = "${INSTALL_PLAYWRIGHT}"
  }

  cache-from = ["type=registry,ref=${BACKEND_REPOSITORY}:latest"]
  cache-to   = ["type=inline"]

  tags      = ["${BACKEND_REPOSITORY}:${TAG}"]
}

target "web" {
  context    = "web"
  dockerfile = "Dockerfile"

  args = {
    NEXT_PUBLIC_OIDC_LOGIN_PROVIDER = "${NEXT_PUBLIC_OIDC_LOGIN_PROVIDER}"
  }

  cache-from = ["type=registry,ref=${WEB_SERVER_REPOSITORY}:latest"]
  cache-to   = ["type=inline"]

  tags      = ["${WEB_SERVER_REPOSITORY}:${TAG}"]
}

target "model-server" {
  context = "backend"

  dockerfile = "Dockerfile.model_server"

  cache-from = ["type=registry,ref=${MODEL_SERVER_REPOSITORY}:latest"]
  cache-to   = ["type=inline"]

  tags      = ["${MODEL_SERVER_REPOSITORY}:${TAG}"]
}

target "integration" {
  context    = "backend"
  dockerfile = "tests/integration/Dockerfile"

  // Provide the base image via build context from the backend target
  contexts = {
    base = "target:backend"
  }

  tags      = ["${INTEGRATION_REPOSITORY}:${TAG}"]
}
