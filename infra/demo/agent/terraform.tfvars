# demo environment values. No secrets here (terraform.md rule 24). image_tag is passed with -var.

state_storage_account_name = "stexampletfstatesea"
state_container_name       = "formapp"
foundation_state_key       = "demo/foundation.tfstate"

image_repository = "api"

# Story 4.1: the hosted agent. Its image is agent:<commit SHA> (the deploy also passes the
# repository with -var). AD-9 ceilings: 0.5 vCPU / 1 GiB, 15-minute idle timeout.
agent_image_repository     = "agent"
agent_cpu                  = "0.5"
agent_memory               = "1Gi"
agent_idle_timeout_seconds = 900
# Keep every agent trace, as for api: demo traffic is low and the workspace's daily cap bounds cost.
telemetry_sampling_ratio = 1.0
