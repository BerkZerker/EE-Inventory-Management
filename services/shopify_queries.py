"""Centralised Shopify GraphQL query and mutation constants.

All GraphQL strings used by the Shopify integration live here so that
``shopify_sync`` and ``reconciliation`` import from a single source of truth.
"""

SEARCH_PRODUCTS_QUERY = """
query SearchProducts($query: String!) {
  products(first: 5, query: $query) {
    edges {
      node {
        id
        title
      }
    }
  }
}
"""

CREATE_PRODUCT_MUTATION = """
mutation CreateProduct($input: ProductInput!) {
  productCreate(input: $input) {
    userErrors {
      field
      message
    }
    product {
      id
      title
    }
  }
}
"""

LOCATIONS_QUERY = """
query { locations(first: 1) { edges { node { id } } } }
"""

CREATE_VARIANTS_MUTATION = """
mutation CreateVariants($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkCreate(productId: $productId, variants: $variants) {
    userErrors {
      field
      message
    }
    productVariants {
      id
      title
      sku
    }
  }
}
"""

GET_PRODUCT_VARIANTS_QUERY = """
query GetProductVariants($id: ID!) {
  product(id: $id) {
    variants(first: 100) {
      edges {
        node {
          id
          selectedOptions {
            name
            value
          }
        }
      }
    }
  }
}
"""

DELETE_VARIANTS_MUTATION = """
mutation DeleteVariants($productId: ID!, $variantsIds: [ID!]!) {
  productVariantsBulkDelete(productId: $productId, variantsIds: $variantsIds) {
    userErrors {
      field
      message
    }
  }
}
"""

PUBLICATIONS_QUERY = """
query {
  publications(first: 20) {
    edges {
      node {
        id
        name
      }
    }
  }
}
"""

PUBLISHABLE_PUBLISH_MUTATION = """
mutation PublishablePublish($id: ID!, $input: [PublicationInput!]!) {
  publishablePublish(id: $id, input: $input) {
    userErrors {
      field
      message
    }
  }
}
"""

RECONCILE_VARIANTS_QUERY = """
query GetProductVariants($id: ID!) {
  product(id: $id) {
    variants(first: 100) {
      edges { node { id sku } }
    }
  }
}
"""
