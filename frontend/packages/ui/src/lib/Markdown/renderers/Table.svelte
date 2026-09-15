<script lang="ts">
  import { type Tokens } from "marked";
  import RenderToken from "./RenderToken.svelte";

  export let token: Tokens.Table;
</script>

<table>
  <thead>
    <tr>
      {#each token.header as cell, i (i)}
        <th scope="col" style={cell.align ? `text-align: ${cell.align};` : undefined}>
          <RenderToken token={cell.tokens} />
        </th>
      {/each}
    </tr>
  </thead>
  <tbody>
    {#each token.rows as row, r (r)}
      <tr>
        {#each row as cell, c (c)}
          <td style={cell.align ? `text-align: ${cell.align};` : undefined}>
            <RenderToken token={cell.tokens} />
          </td>
        {/each}
      </tr>
    {/each}
  </tbody>
</table>
