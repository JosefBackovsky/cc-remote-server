# cc-remote-services

Docker images for the [cc-remote](https://github.com/JosefBackovsky/cc-remote) platform.

## Components

| Component | Directory | Image | Status |
|-----------|-----------|-------|--------|
| [Portal](portal/) | `portal/` | `josefbackovsky/cc-remote-portal` | Active |
| [Firewall](firewall/) | `firewall/` | `josefbackovsky/cc-remote-firewall` | Active |

## CI/CD

Push to `main` triggers GitHub Actions build for changed components only (path-filtered). Images are pushed to Docker Hub with `latest` and git SHA tags.

## Usage

```bash
# Pull any component
docker pull josefbackovsky/cc-remote-portal:latest

# Build locally
docker build -t portal portal/
```
