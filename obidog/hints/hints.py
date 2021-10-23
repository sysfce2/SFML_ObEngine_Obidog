from collections import defaultdict
import os
import re
from typing import Dict, List, Union

from mako.template import Template
from mako.lookup import TemplateLookup
from obidog.bindings.generator import discard_placeholders

from obidog.converters.lua.types import LuaType, convert_all_types
from obidog.databases import CppDatabase
from obidog.logger import log
from obidog.models.classes import AttributeModel, ClassModel
from obidog.models.functions import FunctionModel
from obidog.models.namespace import NamespaceModel
from obidog.models.qualifiers import QualifiersModel
from obidog.converters.lua.types import DYNAMIC_TYPES, DynamicTupleType

# TODO: rename p0, p1, p2 to proper parameter names

MANUAL_TYPES = {
    "Engine": "obe.Engine.Engine",
    "This": "obe.Script.GameObject",
    "Event": "obe.Events._EventTable",
    "Object": "table<string, any>",
}


def write_hints(
    tables: List[str],
    elements: List[Union[ClassModel, NamespaceModel, FunctionModel, AttributeModel]],
):
    lookup = TemplateLookup(["templates/hints"])
    with open("templates/hints/lua_class.mako", "r", encoding="utf-8") as tpl:
        class_tpl = Template(tpl.read(), lookup=lookup)
    with open("templates/hints/lua_function.mako", "r", encoding="utf-8") as tpl:
        function_tpl = Template(tpl.read(), lookup=lookup)
    with open("templates/hints/lua_enum.mako", "r", encoding="utf-8") as tpl:
        enum_tpl = Template(tpl.read(), lookup=lookup)
    with open("templates/hints/lua_global.mako", "r", encoding="utf-8") as tpl:
        global_tpl = Template(tpl.read(), lookup=lookup)
    with open("templates/hints/lua_typedef.mako", "r", encoding="utf-8") as tpl:
        typedef_tpl = Template(tpl.read(), lookup=lookup)
    hints = [f"{table} = {{}};\n" for table in tables]
    hints += ["\n"]

    for element in elements:
        if element._type == "class":
            hints.append(class_tpl.get_def("lua_class").render(klass=element))
        elif element._type == "function":
            hints.append(function_tpl.get_def("lua_function").render(function=element))
        elif element._type == "enum":
            hints.append(enum_tpl.get_def("lua_enum").render(enum=element))
        elif element._type == "global":
            hints.append(global_tpl.get_def("lua_global").render(glob=element))
        elif element._type == "typedef":
            hints.append(typedef_tpl.get_def("lua_typedef").render(typedef=element))
    hints += ["\n\n"]
    hints += [
        f"---@type {manual_type_value}\n{manual_type_name} = {{}};\n\n"
        for manual_type_name, manual_type_value in MANUAL_TYPES.items()
    ]
    with open(
        os.path.join("export", "hints.lua"),
        "w",
        encoding="utf-8",
    ) as export:
        export.write("".join(hints))


def _add_return_type_to_constructors(cpp_db: CppDatabase):
    for class_value in cpp_db.classes.values():
        for constructor in class_value.constructors:
            lua_class_name = (
                f"{class_value.namespace.replace('::', '.')}.{class_value.name}"
            )
            constructor.return_type = LuaType(type=lua_class_name)
            if not constructor.description:
                constructor.description = f"{lua_class_name} constructor"


def _remove_operators(cpp_db: CppDatabase):
    for class_value in cpp_db.classes.values():
        operators_to_pop = []
        for method_name, method in class_value.methods.items():
            if re.search(r"^operator\W", method.name):
                operators_to_pop.append(method_name)
        for method_name in operators_to_pop:
            class_value.methods.pop(method_name)


def _get_namespace_tables(elements):
    return sorted(
        list(
            set(
                [
                    element.namespace.replace("::", ".")
                    for element in elements
                    if hasattr(element, "namespace") and element.namespace
                ]
            )
        ),
        key=lambda s: s.count("."),
    )


def _fix_bind_as(elements: List[Union[FunctionModel, ClassModel, AttributeModel]]):
    for element in elements:
        if element.flags.bind_to:
            element.name = element.flags.bind_to
        if isinstance(element, ClassModel):
            _fix_bind_as(element.methods.values())
            _fix_bind_as(element.attributes.values())


def _setup_methods_as_attributes(classes: Dict[str, ClassModel]):
    for class_value in classes.values():
        methods_to_pop = []
        for method_name, method in class_value.methods.items():
            if method.flags.as_property:
                methods_to_pop.append(method_name)
                class_value.attributes[method.name] = AttributeModel(
                    name=method.name,
                    namespace=method.namespace,
                    type=method.return_type,
                    qualifiers=QualifiersModel(
                        method.qualifiers.const, method.qualifiers.static
                    ),
                    description=method.description,
                    flags=method.flags,
                    export=method.export,
                    location=method.location,
                    visibility=method.visibility,
                    urls=method.urls,
                )
        for method in methods_to_pop:
            class_value.methods.pop(method)


def _build_table_for_events(classes: Dict[str, ClassModel]):
    result = {}
    events = []
    for class_value in classes.values():
        if class_value.namespace.startswith("obe::Events::"):
            events.append(class_value)
    events_grouped_by_section = defaultdict(list)
    for event in events:
        if "id" not in event.attributes:
            continue
        event_id = (
            event.attributes["id"]
            .initializer.strip()
            .removeprefix("=")
            .strip()
            .removeprefix('"')
            .removesuffix('"')
        )
        events_grouped_by_section[event.namespace.removeprefix("obe::Events::")].append(
            (event_id, event)
        )

    event_groups = {}
    for event_group_name, events in events_grouped_by_section.items():
        event_group_attributes = {
            event_id: AttributeModel(
                name=event_id,
                type=LuaType(f"fun(evt:obe.Events.{event_group_name}.{event.name})"),
                namespace=event.namespace,
            )
            for event_id, event in events
        }
        event_groups[event_group_name] = ClassModel(
            name=event_group_name,
            namespace="obe::Events::_EventTableGroups",
            attributes=event_group_attributes,
            constructors=[],
            methods={},
        )

    event_groups_as_attributes = {}
    for event_group_name, event_group in event_groups.items():
        event_groups_as_attributes[event_group_name] = AttributeModel(
            name=event_group.name,
            namespace=event_group.namespace,
            type=LuaType(f"obe.Events._EventTableGroups.{event_group_name}"),
        )

    event_namespace = ClassModel(
        name="_EventTable",
        namespace="obe::Events",
        attributes=event_groups_as_attributes,
        constructors=[],
        methods={},
    )

    for event_group_name, event_group in event_groups.items():
        result[f"{event_group.namespace}::{event_group.name}"] = event_group
    result["obe::Events::_EventTable"] = event_namespace

    return result


def _generate_dynamic_tuple(
    tuple_name: str, tuple_type: DynamicTupleType
) -> ClassModel:
    return ClassModel(
        tuple_name,
        "",
        attributes={
            f"[{i}]": AttributeModel(
                name=f"[{i}]",
                type=sub_type,
                namespace="",
            )
            for i, sub_type in enumerate(tuple_type.sub_types)
        },
        constructors=[],
        methods={},
    )


def _generate_dynamic_types() -> Dict[str, ClassModel]:
    result = {}
    for dynamic_type_name, dynamic_type in DYNAMIC_TYPES.dynamic_types.items():
        if isinstance(dynamic_type, DynamicTupleType):
            result[dynamic_type_name] = _generate_dynamic_tuple(
                dynamic_type_name, dynamic_type
            )
    return result


def generate_hints(cpp_db: CppDatabase, path_to_doc: str):
    log.info("Discarding placeholders")
    discard_placeholders(cpp_db)

    log.info("Converting all types")
    convert_all_types(cpp_db)

    cpp_db.classes |= _build_table_for_events(cpp_db.classes)
    cpp_db.classes |= _generate_dynamic_types()
    all_elements = [
        item
        for item_type in cpp_db.__dict__.keys()
        for item in getattr(cpp_db, item_type).values()
        if not item.flags.nobind
    ]

    _add_return_type_to_constructors(cpp_db)
    _remove_operators(cpp_db)

    _fix_bind_as(all_elements)
    _setup_methods_as_attributes(cpp_db.classes)

    log.info("Generating hints")
    write_hints(_get_namespace_tables(all_elements), all_elements)