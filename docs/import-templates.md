# Import Templates

Download these UTF-8 CSV templates from the Products or Orders screen:

- [Product catalog template](../frontend/public/templates/product-catalog-template.csv)
- [Sales orders template](../frontend/public/templates/sales-orders-template.csv)

## Product Catalog

Fill in `sku` and `name` for every product. `name_en`, `description`, `price`, `stock_quantity`, `status`, `category`, `suitable_for`, `colors`, `sizes`, and `keywords` are also accepted. Separate multiple facet values with commas or semicolons. Use `active` or `archived` for `status`.

Importing a new SKU creates a product. Importing an existing SKU adds `stock_quantity` to its current inventory; it does not replace the saved name or price. Use `0` when an existing SKU should receive no stock. Preview the file and confirm the result before importing. The file is idempotent by default; deliberately receiving the same file again requires an explicit repeat confirmation in the UI/API flow.

Product links are edited in the product form, not this CSV: the current product CSV importer does not accept a link column. Only HTTP(S) links are saved and opened in a new tab with opener protections.

## Sales Orders

Required columns are `order_number`, `customer_id`, `sku`, and `quantity`. `conversation_id` is optional. Use an existing customer ID and an existing product SKU from the same shop. Put each product on its own row; rows with the same order number are grouped into one order and must use the same customer and conversation IDs.

Preview before importing. The import creates draft orders only and uses current catalog prices. It does not confirm orders, reserve stock, or accept customer names in place of IDs. Never add real customer details to example or shared template files.

The templates contain headers only so they cannot accidentally create products or orders when opened or imported without being filled in.