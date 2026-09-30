import { NodeTypes } from "@vue/compiler-dom";
import { parse } from "@vue/compiler-sfc";

const translatableAttributes = new Set(["alt", "aria-label", "placeholder", "title"]);
const hasVietnameseText = (value) => [...String(value)].some((character) => (
  character.codePointAt(0) > 127 && /\p{Script=Latin}/u.test(character)
));

function jsString(value) {
  return JSON.stringify(value).replaceAll("'", "\\u0027");
}

export function transformVueTemplateText(source, filename = "component.vue") {
  const { descriptor, errors } = parse(source, { filename });
  const template = descriptor.template;
  if (errors.length || !template?.ast) return source;

  const replacements = [];
  function visit(node) {
    if (node.type === NodeTypes.TEXT && node.content.trim()) {
      replacements.push({
        start: node.loc.start.offset,
        end: node.loc.end.offset,
        text: `{{ $t(${jsString(node.content)}) }}`,
      });
    }
    if (node.type === NodeTypes.INTERPOLATION && hasVietnameseText(node.content?.content)) {
      replacements.push({
        start: node.content.loc.start.offset,
        end: node.content.loc.end.offset,
        text: `$t(${node.content.content})`,
      });
    }
    if (node.type === NodeTypes.ELEMENT) {
      for (const prop of node.props) {
        if (prop.type === NodeTypes.ATTRIBUTE && translatableAttributes.has(prop.name) && prop.value) {
          replacements.push({
            start: prop.loc.start.offset,
            end: prop.loc.end.offset,
            text: `:${prop.name}='$t(${jsString(prop.value.content)})'`,
          });
        }
        if (prop.type === NodeTypes.DIRECTIVE && prop.name === "bind" && hasVietnameseText(prop.exp?.content)) {
          replacements.push({
            start: prop.exp.loc.start.offset,
            end: prop.exp.loc.end.offset,
            text: `$t(${prop.exp.content})`,
          });
        }
      }
    }
    for (const child of node.children || []) visit(child);
  }
  visit(template.ast);

  let output = source;
  replacements.sort((a, b) => b.start - a.start);
  for (const item of replacements) {
    output = output.slice(0, item.start) + item.text + output.slice(item.end);
  }
  return output;
}

export function localizeVueTemplatePlugin() {
  return {
    name: "localize-vue-template-text",
    enforce: "pre",
    transform(source, id) {
      if (!id.endsWith(".vue") || (!id.includes("/src/") && !id.includes("\\src\\"))) return null;
      const transformed = transformVueTemplateText(source, id);
      return transformed === source ? null : { code: transformed, map: null };
    },
  };
}
