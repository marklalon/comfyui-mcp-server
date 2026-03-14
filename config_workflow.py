#!/usr/bin/env python
"""
Interactive CLI tool to configure ComfyUI workflows for MCP parameters.

This tool allows users to:
1. Select a workflow file from the workflows/ directory
2. Configure input nodes to become MCP parameters (PARAM_*)
3. Configure output nodes to set output_preferences
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Constants matching workflow_manager.py
PLACEHOLDER_PREFIX = "PARAM_"
PLACEHOLDER_TYPE_HINTS = {
    "STR": str,
    "STRING": str,
    "TEXT": str,
    "INT": int,
    "FLOAT": float,
    "BOOL": bool,
}

# Input node type mapping: class_type -> {input_field: type}
INPUT_NODE_MAPPING = {
    "LoadImage": {"image": str},
    "PrimitiveInt": {"value": int},
    "PrimitiveFloat": {"value": float},
    "PrimitiveString": {"value": str},
    "PrimitiveStringMultiline": {"value": str},
    "CLIPTextEncode": {"text": str},
    "CLIPTextEncodeSDXL": {"text_g": str, "text_l": str},
    "EmptyLatentImage": {"width": int, "height": int, "batch_size": int},
    "EmptyLatentImageFromCPU": {"width": int, "height": int, "batch_size": int},
    "EmptyLatentAudio": {"width": int, "batch_size": int},
    "KSampler": {"seed": int},
    "KSamplerAdvanced": {"seed": int},
    "SamplerCustom": {"seed": int},
}

# Output node types and their corresponding output keys
OUTPUT_NODE_MAPPING = {
    "SaveImage": ("images", "image"),
    "PreviewImage": ("images", "image"),
    "SaveAnimatedWEBP": ("images", "gif"),
    "SaveAnimatedPNG": ("images", "gif"),
    "SaveAudio": ("audio", "audios", "sound", "files"),
    "SaveAudioMP3": ("audio", "audios", "sound", "files"),
    "VHS_SaveVideo": ("videos", "video", "mp4"),
    "VideoCombine": ("videos", "video", "mp4"),
    "SaveVideo": ("videos", "video", "mp4"),
    "PreviewAny": ("text", "texts", "string", "strings", "ui"),
}

# Type inference from field names
FIELD_TYPE_INFERENCE = {
    "seed": int,
    "width": int,
    "height": int,
    "batch_size": int,
    "seconds": int,
    "duration": int,
    "fps": int,
    "text": str,
    "prompt": str,
    "image": str,
    "value": str,
}

# Fields that should always use field name (not node title) for parameter name
PREFER_FIELD_NAME = {
    "seed", "prompt", "text",
    "width", "height", "batch_size", "fps", "duration", "seconds",
    "image", "image2", "image3",
}

# Enum constraints for known combo-type fields: field_name -> allowed values
FIELD_ENUM_CONSTRAINTS: Dict[str, List[str]] = {}

# Keywords to extract from node titles for parameter naming
# Maps keyword (lowercase) to preferred parameter name
NODE_TITLE_KEYWORDS = {
    "prompt": "prompt",
    "positive": "positive_prompt",
    "negative": "negative_prompt",
    "text": "text",
}


PRIMITIVE_NODE_TYPES = {"PrimitiveInt", "PrimitiveFloat", "PrimitiveString", "PrimitiveStringMultiline"}


class WorkflowConfigurator:
    def __init__(self, workflows_dir: Path):
        self.workflows_dir = workflows_dir
        self.workflow: Dict[str, Any] = {}
        self.workflow_path: Optional[Path] = None
        self.changes: List[str] = []
        self.collected_defaults: Dict[str, Any] = {}
        self.collected_constraints: Dict[str, Any] = {}

    def discover_workflows(self) -> List[Path]:
        """Find all workflow JSON files in the workflows directory."""
        if not self.workflows_dir.exists():
            return []
        workflows = []
        for f in sorted(self.workflows_dir.glob("*.json")):
            if not f.name.endswith(".meta.json"):
                workflows.append(f)
        return workflows

    def select_workflow(self, workflow_path: Optional[str] = None) -> bool:
        """Select a workflow file to configure."""
        workflows = self.discover_workflows()

        if not workflows:
            print("No workflow files found in the workflows directory.")
            return False

        if workflow_path:
            # Direct path specified
            path = Path(workflow_path)
            if path.exists():
                self.workflow_path = path
            else:
                # Try relative to workflows dir
                path = self.workflows_dir / workflow_path
                if path.exists():
                    self.workflow_path = path
                elif path.with_suffix(".json").exists():
                    # Try adding .json extension
                    self.workflow_path = path.with_suffix(".json")
                else:
                    print(f"Workflow file not found: {workflow_path}")
                    return False
        else:
            # Interactive selection
            print("\nAvailable workflows:")
            print("-" * 40)
            for i, wf in enumerate(workflows, 1):
                print(f"  {i}. {wf.stem}")
            print("-" * 40)

            while True:
                try:
                    choice = input("\nSelect a workflow (number or name): ").strip()
                    if not choice:
                        return False
                    
                    # Try as number first
                    try:
                        idx = int(choice) - 1
                        if 0 <= idx < len(workflows):
                            self.workflow_path = workflows[idx]
                            break
                    except ValueError:
                        pass
                    
                    # Try as name
                    for wf in workflows:
                        if wf.stem.lower() == choice.lower():
                            self.workflow_path = wf
                            break
                    
                    if self.workflow_path:
                        break
                    
                    print(f"Invalid selection: {choice}")
                except (EOFError, KeyboardInterrupt):
                    print("\nCancelled.")
                    return False

        # Load the workflow
        try:
            with open(self.workflow_path, "r", encoding="utf-8") as f:
                self.workflow = json.load(f)
            print(f"\nLoaded workflow: {self.workflow_path.name}")
            return True
        except (json.JSONDecodeError, IOError) as e:
            print(f"Failed to load workflow: {e}")
            return False

    def scan_input_nodes(self) -> List[Tuple[str, str, str, Any, type]]:
        """
        Scan workflow for configurable input nodes.
        Returns: List of (node_id, class_type, input_name, current_value, inferred_type)
        """
        inputs = []

        for node_id, node in self.workflow.items():
            if not isinstance(node, dict) or node_id == "_meta":
                continue

            class_type = node.get("class_type", "")
            node_inputs = node.get("inputs", {})

            # Get configurable fields for this node type
            config_fields = INPUT_NODE_MAPPING.get(class_type, {})

            for input_name, current_value in node_inputs.items():
                # Skip connection links (lists)
                if isinstance(current_value, list):
                    continue

                # Check if this field is configurable
                if input_name in config_fields:
                    inferred_type = config_fields[input_name]
                elif input_name in FIELD_TYPE_INFERENCE:
                    inferred_type = FIELD_TYPE_INFERENCE[input_name]
                else:
                    continue  # Skip non-configurable fields

                # Check if already a PARAM_ placeholder
                if isinstance(current_value, str) and current_value.startswith(PLACEHOLDER_PREFIX):
                    status = f"[MCP: {current_value}]"
                else:
                    status = f"[Value: {current_value!r}]"

                inputs.append((node_id, class_type, input_name, current_value, inferred_type, status))

        return inputs

    def scan_output_nodes(self) -> List[Tuple[str, str, str]]:
        """
        Scan workflow for output nodes.
        Returns: List of (node_id, class_type, output_keys)
        """
        outputs = []

        for node_id, node in self.workflow.items():
            if not isinstance(node, dict) or node_id == "_meta":
                continue

            class_type = node.get("class_type", "")
            if class_type in OUTPUT_NODE_MAPPING:
                output_keys = OUTPUT_NODE_MAPPING[class_type]
                outputs.append((node_id, class_type, output_keys))

        return outputs

    def _find_consumer_input_name(self, node_id: str) -> Optional[str]:
        """
        Find what input name other nodes use to reference this node.
        
        For example, if node 86 is referenced as:
          "image2": ["86", 0] in node 73
        then return "image2".
        
        This helps determine the correct parameter name for LoadImage nodes
        that are connected to downstream nodes with specific input names.
        
        Returns: The input name used by consumer nodes, or None.
        """
        for other_node in self.workflow.values():
            if not isinstance(other_node, dict):
                continue
            inputs = other_node.get("inputs", {})
            for input_name, value in inputs.items():
                # Check if this is a connection link to our node
                if isinstance(value, list) and len(value) == 2:
                    if str(value[0]) == str(node_id):
                        return input_name
        return None

    def generate_placeholder(self, param_name: str, param_type: type) -> str:
        """Generate a PARAM_ placeholder with optional type prefix."""
        name = self._normalize_name(param_name).upper()

        # Add type prefix for non-string types
        if param_type is int:
            return f"{PLACEHOLDER_PREFIX}INT_{name}"
        elif param_type is float:
            return f"{PLACEHOLDER_PREFIX}FLOAT_{name}"
        elif param_type is bool:
            return f"{PLACEHOLDER_PREFIX}BOOL_{name}"
        else:
            return f"{PLACEHOLDER_PREFIX}{name}"

    def _normalize_name(self, raw: str) -> str:
        """Normalize a parameter name."""
        cleaned = [
            (char.lower() if char.isalnum() else "_")
            for char in raw.strip()
        ]
        return "".join(cleaned).strip("_") or "param"

    def _extract_keyword_from_title(self, title: str) -> Optional[str]:
        """
        Extract a meaningful keyword from node title for parameter naming.
        
        For example:
        - "CLIP Text Encode (Prompt)" -> "prompt"
        - "CLIP Text Encode (Positive)" -> "positive_prompt"
        - "CLIP Text Encode (Negative)" -> "negative_prompt"
        
        Returns: The extracted parameter name, or None if no keyword found.
        """
        title_lower = title.lower()
        for keyword, param_name in NODE_TITLE_KEYWORDS.items():
            if keyword in title_lower:
                return param_name
        return None

    def configure_inputs(self) -> None:
        """Interactive input parameter configuration."""
        inputs = self.scan_input_nodes()

        if not inputs:
            print("\nNo configurable input nodes found.")
            return

        print("\n" + "=" * 60)
        print("INPUT NODES")
        print("=" * 60)

        for i, (node_id, class_type, input_name, current_value, inferred_type, status) in enumerate(inputs, 1):
            node_meta = self.workflow.get(node_id, {}).get("_meta", {})
            node_title = node_meta.get("title", class_type)

            print(f"\n[{i}] Node: {node_title} ({class_type})")
            print(f"    ID: {node_id}")
            print(f"    Field: {input_name}")
            print(f"    Type: {inferred_type.__name__}")
            print(f"    Current: {status}")

            # Skip if already a PARAM_
            if isinstance(current_value, str) and current_value.startswith(PLACEHOLDER_PREFIX):
                print("    -> Already configured as MCP parameter.")
                continue

            # Ask if user wants to configure
            try:
                choice = input("    Configure as MCP parameter? [Y/n]: ").strip().lower()
                if choice == "n":
                    continue

                # Determine parameter name priority:
                # 1. Consumer input name (what downstream nodes call this input)
                #    - Primitive nodes: always prefer consumer name (e.g. "target_count")
                #    - Other nodes: only if it's a well-known field name
                # 2. Keyword extracted from node title (e.g. "Prompt" -> "prompt")
                # 3. Well-known field name (seed, width, height, etc.)
                # 4. Node title normalized
                # 5. Field name as fallback
                consumer_input_name = self._find_consumer_input_name(node_id)

                if class_type in PRIMITIVE_NODE_TYPES and consumer_input_name:
                    # Primitive nodes: use the consumer's input name as it describes the purpose
                    param_name = self._normalize_name(consumer_input_name)
                elif consumer_input_name and consumer_input_name in PREFER_FIELD_NAME:
                    param_name = consumer_input_name
                elif input_name in ("text", "value") and node_meta.get("title"):
                    # For text/value fields, try to extract keyword from node title FIRST
                    # e.g., "CLIP Text Encode (Prompt)" -> "prompt"
                    node_title = node_meta.get("title", "")
                    extracted_name = self._extract_keyword_from_title(node_title)
                    if extracted_name:
                        param_name = extracted_name
                    else:
                        param_name = self._normalize_name(node_title)
                elif input_name in PREFER_FIELD_NAME:
                    param_name = input_name
                else:
                    node_title = node_meta.get("title", "")
                    if node_title:
                        param_name = self._normalize_name(node_title)
                    else:
                        param_name = input_name

                # Generate placeholder
                placeholder = self.generate_placeholder(param_name, inferred_type)

                # Update workflow
                self.workflow[node_id]["inputs"][input_name] = placeholder
                self.changes.append(f"Input: {input_name} -> {placeholder}")
                print(f"    -> Set to: {placeholder}")

                # Save default value
                if class_type in PRIMITIVE_NODE_TYPES and not isinstance(current_value, str):
                    # Primitive nodes: auto-save current value as default
                    self.collected_defaults[param_name] = current_value
                    self.changes.append(f"Default: {param_name} = {current_value!r}")
                    print(f"    -> Default saved: {param_name} = {current_value!r}")
                elif input_name in FIELD_ENUM_CONSTRAINTS:
                    # Enum fields: auto-save current value (or first option) as default, save constraints
                    enum_values = FIELD_ENUM_CONSTRAINTS[input_name]
                    default_value = current_value if current_value in enum_values else enum_values[0]
                    self.collected_defaults[param_name] = default_value
                    self.changes.append(f"Default: {param_name} = {default_value!r}")
                    print(f"    -> Default saved: {param_name} = {default_value!r}")
                    self.collected_constraints[param_name] = {"enum": enum_values}
                    self.changes.append(f"Constraint: {param_name} enum = {enum_values}")
                    print(f"    -> Enum constraint saved: {enum_values}")

            except (EOFError, KeyboardInterrupt):
                print("\n")
                return

    def show_output_nodes(self) -> None:
        """Display detected output nodes (informational only)."""
        outputs = self.scan_output_nodes()

        if not outputs:
            print("\nNo output nodes found.")
            return

        print("\n" + "=" * 60)
        print("OUTPUT NODES (for reference)")
        print("=" * 60)

        for node_id, class_type, output_keys in outputs:
            node_meta = self.workflow.get(node_id, {}).get("_meta", {})
            node_title = node_meta.get("title", class_type)
            print(f"\n  Node: {node_title} ({class_type})")
            print(f"    ID: {node_id}")
            print(f"    Output keys: {output_keys}")

    def save(self) -> bool:
        """Save the configured workflow."""
        if not self.changes:
            print("\nNo changes to save.")
            return False

        print("\n" + "=" * 60)
        print("CHANGES SUMMARY")
        print("=" * 60)
        for change in self.changes:
            print(f"  - {change}")

        try:
            confirm = input("\nSave changes? [Y/n]: ").strip().lower()
            if confirm == "n":
                print("Changes discarded.")
                return False
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return False

        # Write updated workflow
        with open(self.workflow_path, "w", encoding="utf-8") as f:
            json.dump(self.workflow, f, indent=2, ensure_ascii=False)

        print(f"Saved: {self.workflow_path.name}")

        # Write collected defaults and constraints to .meta.json
        if self.collected_defaults or self.collected_constraints:
            meta_path = self.workflow_path.with_suffix(".meta.json")
            meta: Dict[str, Any] = {}
            if meta_path.exists():
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                except (json.JSONDecodeError, IOError):
                    pass
            if self.collected_defaults:
                existing = meta.get("defaults", {})
                existing.update(self.collected_defaults)
                meta["defaults"] = existing
            if self.collected_constraints:
                existing_constraints = meta.get("constraints", {})
                existing_constraints.update(self.collected_constraints)
                meta["constraints"] = existing_constraints
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)
            print(f"Saved defaults/constraints to: {meta_path.name}")

        return True


def main():
    parser = argparse.ArgumentParser(
        description="Configure ComfyUI workflows for MCP parameters",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python config_workflow.py
  python config_workflow.py --workflow generate_image
  python config_workflow.py -w workflows/generate_image.json
        """
    )
    parser.add_argument(
        "-w", "--workflow",
        type=str,
        default=None,
        help="Workflow file name or path to configure"
    )
    parser.add_argument(
        "--workflows-dir",
        type=str,
        default=None,
        help="Path to workflows directory (default: ./workflows)"
    )

    args = parser.parse_args()

    # Determine workflows directory
    script_dir = Path(__file__).parent
    workflows_dir = Path(args.workflows_dir) if args.workflows_dir else script_dir / "workflows"

    # Run configurator
    configurator = WorkflowConfigurator(workflows_dir)

    if not configurator.select_workflow(args.workflow):
        return 1

    # Run configuration steps
    configurator.configure_inputs()
    configurator.show_output_nodes()

    # Save if there are changes
    if configurator.save():
        print("\nWorkflow configuration complete!")
    else:
        print("\nNo changes saved.")

    return 0


if __name__ == "__main__":
    exit(main())
