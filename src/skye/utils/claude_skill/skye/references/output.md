# The answer format: `output`

To get JSON, a table or XML back, declare an `output` block; never write the schema, the table header or the XML by hand in a `text`.
The renderer appends the instructions to the last user message.

```skye
prompt "products" {
  variables = { catalogue = string }
  output "table" { name = string, price = number, in_stock = bool }
  message "user" { text = "List the products in this catalogue:\n{{ catalogue }}" }
}

prompt "extract_invoice" {
  variables = { document = string }
  output "json" {
    vendor   = string          "Seller name as printed on the invoice"
    currency = string("EUR")   "ISO 4217 currency code"
    lines    = list({
      description = string    "Text of the line"
      amount      = number    "Amount of the line"
    })                         "One entry per invoice line"
    meta     = map({ source = string })
  }
  message "user" { text = "{{ document }}" }
}
```

- The format is `"json"`, `"table"`, `"xml"` or `"text"` (plain answer, no fields, optional `style = "a short paragraph"`); `output { ... }` with no label is `"json"`. At most one unconditional `output` block per
  prompt, in the prompt (not in a message), or conditional ones (below), never both.
- Conditional outputs: to let a variable choose the shape, put each `output` in a top-level `when` (a `when` nested in one works too;
  never inside a `message` or an `each`). Write conditions that exclude each other: at render time exactly the one that holds is used,
  none means free text, two at once raise `ValidationError`. For "the caller's fields, else defaults":

  ```
  variables = { schema = map({}) "Output fields, optional", format = string("json") }
  when schema     { output format { schema = schema } }
  when not schema { output format { name = string "What the extracted item is", value = string "Its value, as written in the input" } }
  ```

  `active_output(spec, variables)` (from `skye.prompts`) returns the active `OutputSpec` or `None`; `skye prompt info` shows one
  `Output (when ...)` section per block. Never write default fields next to `schema = VAR`: that is an error.
- Field types: `string`, `number`, `bool`, `list`, `map`; a default makes a field optional (`string("EUR")`); `list(string)` or `[string]`;
  `list({ ... })` for a list of objects; `map({ ... })` or `{ ... }` for an object.
- Description: a string right after the type (`total = number "Total amount including VAT"`), also after the `)` / `}` of a list or map
  and in the comma form (`{ a = string "x", b = number }`). It goes into the instructions for the model (JSON Schema `"description"`,
  `- total: number — ...` in a table, `<total>number — ...</total>` in XML). Use it whenever the field name alone is ambiguous. Never
  write a `description = "..."` field or a `#` comment for this: a comment is not sent to the model, and a field named `description` is a
  field of the answer. Only an `output` block and the `variables` map of a prompt accept the trailing string.
- `table`: scalar columns only (string, number, bool), one row per item; a list or map column is an error.
- `xml`: the root element is the prompt name in snake_case, a list is repeated `<item>` elements.
- Dynamic fields: `output "json" { schema = fields }` (or `output format { schema = fields }`) with `fields = map` declared in `variables`; its value is
  `{"name": "string", "tags": ["string"], "vendor": {"city": "string"}, "total": {"type": "number", "description": "With VAT"}}`
  (a field is a type word, `[type]`, a nested map, or `{"type": ..., "description": ...}`, with `"items"` for a `"list"` and
  `"properties"` for a `"map"`). `schema` is reserved and is then the only entry of the block (another field next to it is an
  error); it takes no description.
- Dynamic format: `output format { ... }` (no quotes) takes the format from a declared `string` variable, whose default, if any, must be
  `json`, `table` or `xml`; any other value at render time is an error, and so is `"table"` with a list or map field. The bundled prompt
  `extraction_generic` does this with its `format` and `schema` variables (`schema` is optional: without it the answer has `name` and
  `value`, as in the example above). In Python the block is `PromptSpec.output`, an `OutputSpec`
  with `format`, `format_from`, `fields` (each an `OutputFieldSpec` with `name`, `type`, `default`, `item_type`, `fields`,
  `description`) and `schema_from`.
- To put DATA into a text in a format, use the filters `tojson`, `toxml("root")` and `totable` (`{{ rows | totable }}`).
