"""Research-only packages for the DMI project.

Nothing in ``dmi_research`` is part of the operational DMI pipeline. Modules
here must not be imported by ``dmi_calculator``, ``dmi_pipeline``, the monthly
release workflows, or any production script. They exist to support
investigations whose conclusions may -- after review -- later be promoted into
the operational codebase through a separate, deliberate change.
"""
