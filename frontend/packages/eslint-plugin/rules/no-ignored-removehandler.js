/** @type {import('eslint').Rule.RuleModule} */
const rule = {
  meta: {
    type: "problem",
    schema: [],
    messages: {
      noIgnore:
        "Do not ignore the returned removeHandler function. Always remove registered handlers once they are no longer needed to avoid memory leaks.",
    },
  },

  create(context) {
    return {
      CallExpression(node) {
        const isHandlerFunction =
          (node.callee.type === "Identifier" &&
            node.callee.name === "registerHandler") ||
          (node.callee.type === "MemberExpression" &&
            node.callee.property.name === "registerHandler");

        const hasCorrectArguments =
          node.arguments.length === 2 &&
          node.arguments[0].type === "Literal" &&
          typeof node.arguments[0].value === "string" &&
          (node.arguments[1].type === "FunctionExpression" ||
            node.arguments[1].type === "ArrowFunctionExpression");

        // A bit hard to narrow this down exactly
        const isWebsocketHandlerFunction =
          isHandlerFunction && hasCorrectArguments;

        const isReturnValueUnused =
          node.parent.type !== "VariableDeclarator" &&
          node.parent.type !== "AssignmentExpression" &&
          node.parent.type !== "ReturnStatement";

        if (isWebsocketHandlerFunction && isReturnValueUnused) {
          context.report({
            node,
            messageId: "noIgnore",
          });
        }
      },
    };
  },
};

export default rule;
