package dev.woody.demo.orders;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = {
        "demo.payment-mode=normal",
        "logging.file.name=target/test-logs/normal.jsonl"
})
@AutoConfigureMockMvc
class OrderApiTest {

    @Autowired
    private MockMvc mvc;

    @Test
    void acceptsOrder() throws Exception {
        mvc.perform(post("/api/v1/orders")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"productId":"book-1","quantity":2}
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.orderId").isNotEmpty())
                .andExpect(jsonPath("$.status").value("ACCEPTED"));
    }

    @Test
    void rejectsInvalidOrder() throws Exception {
        mvc.perform(post("/api/v1/orders")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"productId":"","quantity":0}
                                """))
                .andExpect(status().isBadRequest());
    }

    @Test
    void healthIsUp() throws Exception {
        mvc.perform(get("/actuator/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UP"));
    }

    @Test
    void rejectsMissingQuantity() throws Exception {
    mvc.perform(post("/api/v1/orders")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content("""
                            {"productId":"book-1"}
                            """))
                            .andExpect(status().isBadRequest());
    }
    
    @Test
    void rejectsNullQuantity() throws Exception {
    mvc.perform(post("/api/v1/orders")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content("""
                            {"productId":"book-1","quantity":null}
                            """))
                            .andExpect(status().isBadRequest());
    }
}